"""Minimal LiveRecall ASR source: fixed audio chunks in, final captions out."""
import json
import subprocess
import time

import numpy as np
from faster_whisper import WhisperModel
from websockets.sync.client import connect

SERVER_URL = "ws://127.0.0.1:8765"
SESSION = "L1"
SAMPLE_RATE = 16000
CHUNK_SEC = 5
CHUNK_BYTES = CHUNK_SEC * SAMPLE_RATE * 2  # each sample is 2 bytes

# Microphone. To use a video file instead: ["-re", "-i", "lecture.mp4"]
AUDIO_INPUT = ["-f", "pulse", "-i", "RDPSource"]   # Microphone input
# AUDIO_INPUT = [] 


class SpeechToTextModel:
    def __init__(self, model_name, threads):
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, language="en", vad_filter=True)
        text = ""
        for segment in segments:
            text = text + segment.text
        return text.strip()


def send_message(ws, message):
    message["session"] = SESSION
    message["source_ts"] = time.time()
    ws.send(json.dumps(message))


def main():
    model = SpeechToTextModel("base.en", 4)

    ffmpeg_command = ["ffmpeg", "-loglevel", "error", "-nostdin"] + AUDIO_INPUT
    # asetpts: number the audio by sample count, because mic timestamps jitter and make ffmpeg print dts warnings
    ffmpeg_command = ffmpeg_command + ["-vn", "-af", "asetpts=N/SR/TB", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    ffmpeg = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE)

    ws = connect(SERVER_URL)
    send_message(ws, {"type": "SOURCE_HELLO"})

    segment_number = 1
    try:
        while True:
            raw_audio = ffmpeg.stdout.read(CHUNK_BYTES)
            if not raw_audio:
                break

            audio = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768
            text = model.transcribe(audio)
            if not text:
                continue

            send_message(ws, {
                "type": "CAPTION_UPDATE",
                "segment": segment_number,
                "revision": 1,
                "final": True,
                "text": text,
            })
            print(f"#{segment_number} {text}", flush=True)
            segment_number = segment_number + 1
    except KeyboardInterrupt:
        print("Stopping")

    ffmpeg.terminate()
    send_message(ws, {"type": "SOURCE_DONE", "segments": segment_number - 1})
    ws.close()


if __name__ == "__main__":
    main()
