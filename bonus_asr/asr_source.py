"""Minimal LiveRecall ASR source: audio chunks in, final and draft captions out."""
import json
import subprocess
import time
import queue
import threading
import asyncio
import signal

import numpy as np
from faster_whisper import WhisperModel
import websockets

SERVER_URL = "ws://127.0.0.1:8765"
SESSION = "L1"
SAMPLE_RATE = 16000
CHUNK_SEC = 1
CHUNK_BYTES = CHUNK_SEC * SAMPLE_RATE * 2  # each sample is 2 bytes
SEGMENT_TIMING_SEC = 5      # Each segment is 5 seconds
FIRST_REVISION_SEC = 2      # Wait for 2s for audio to stabalize before parsing it to ASR model
MAX_QUEUE_CHUNKS = 30        # at most 30 * 1 = 30 s of waiting audio

# Microphone. To use a video file instead: ["-re", "-i", "lecture.mp4"]
AUDIO_INPUT = ["-f", "pulse", "-i", "RDPSource"]   # Microphone input

# Initialize audio queue to keep audio chunks from ffmpeg
audio_queue = queue.Queue()

class SpeechToTextModel:
    def __init__(self, model_name, threads):
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, language="en", vad_filter=True)
        text = ""
        for segment in segments:
            text = text + segment.text
        return text.strip()

# Read Audio in chunks, and enqueue into the queue
def read_audio(ffmpeg):
    while True:
        raw_audio = ffmpeg.stdout.read(CHUNK_BYTES)
        # There is no more raw audio
        if not raw_audio:
            audio_queue.put(None)
            break
        if audio_queue.qsize() >= MAX_QUEUE_CHUNKS:
            audio_queue.get_nowait()  # drop the oldest chunk
            print("Dropped {CHUNK_SEC}s of audio", flush=True)
        audio_queue.put((time.time(), raw_audio))

async def send_message(ws, message, source_ts):
    message["session"] = SESSION
    message["source_ts"] = source_ts
    await ws.send(json.dumps(message))

async def main():
    model = SpeechToTextModel("base.en", 4)

    async with websockets.connect(SERVER_URL, max_size=2**20) as ws:
        await send_message(ws, {"type": "SOURCE_HELLO"}, time.time())
        print("Caption server has finished initializing and connected to source")

        # Claude guided me on how to read the input from the mic/video
        ffmpeg_command = ["ffmpeg", "-loglevel", "error", "-nostdin"] + AUDIO_INPUT
        # asetpts: number the audio by sample count, because mic timestamps jitter and make ffmpeg print dts warnings
        ffmpeg_command = ffmpeg_command + ["-vn", "-af", "asetpts=N/SR/TB", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
        ffmpeg = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE, start_new_session=True)
        threading.Thread(target=read_audio, args=(ffmpeg,), daemon=True).start()
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, ffmpeg.terminate)

        segment_number = 1      # Which segment number is this
        revision = 0            # Last revision sent for this segment, 0 if none sent yet
        audio_buffer = b""      # To concatenate the audio chunks
        seconds = 0             
        last_text = ""          
        try:
            while True:

                # Dequeue item and timestamp from queue
                item = await asyncio.to_thread(audio_queue.get)
                if item is None:
                    break
                chunk_time, raw_audio = item

                audio_buffer = audio_buffer + raw_audio     # Append the audio to this buffer
                seconds = seconds + CHUNK_SEC
                if seconds < FIRST_REVISION_SEC:           
                    continue

                # Pass it to ASR to transcribe
                audio = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768
                text = await asyncio.to_thread(model.transcribe, audio)
                if text:
                    last_text = text

                final = seconds >= SEGMENT_TIMING_SEC

                # Sends the caption update to server
                if last_text:
                    revision = revision + 1
                    await send_message(ws, {
                        "type": "CAPTION_UPDATE",
                        "segment": segment_number,
                        "revision": revision,
                        "final": final,
                        "text": last_text,
                    }, chunk_time)
                    print(f"#{segment_number} rev {revision} {'FINAL' if final else 'draft'} {last_text}", flush=True)

                # Start the next segment, reset all of the variables except segment number
                if final:
                    if last_text:
                        segment_number = segment_number + 1
                    revision = 0
                    audio_buffer = b""
                    seconds = 0
                    last_text = ""

        finally:
            # Close the input
            ffmpeg.terminate()
            ffmpeg.wait()

        # Stopped partway through a segment, so send the final revision
        if revision > 0:
            await send_message(ws, {
                "type": "CAPTION_UPDATE",
                "segment": segment_number,
                "revision": revision + 1,
                "final": True,
                "text": last_text,
            }, chunk_time)
            segment_number = segment_number + 1

        print("Stopping")
        await send_message(ws, {"type": "SOURCE_DONE", "segments": segment_number - 1}, time.time())


if __name__ == "__main__":
    asyncio.run(main())
