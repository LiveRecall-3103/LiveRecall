# Optional Bonus: Real-Lecture ASR Integration

This folder is intentionally separate from the mandatory deterministic assignment path.

If your team attempts the bonus, connect a local/open-source ASR engine to the **same** LiveRecall protocol, `solution_server.py`, and browser client. Do not make ASR packages mandatory for `pip install -r requirements.txt` or for instructor performance evaluation.

Possible tools include faster-whisper, whisper.cpp, or Vosk. Speech-recognition accuracy/model size is not part of the mandatory networking score. Follow the assignment specification for the current bonus requirements.

## ASR source

`asr_source.py` captions audio with faster-whisper (`base.en`, CPU) while it plays and sends the captions as a normal LiveRecall source. `solution_server.py` and the browser client are unchanged.

System needs: ffmpeg. The first run downloads the model (about 150 MB). Whisper needs about 4 CPU cores to keep up with live audio; on fewer cores it falls behind, prints `Dropped 1s of audio`, and the captions lag.

Set up both environments from the repo root (`venv` for the server, `asr-venv` for the ASR source):

```bash
sudo apt install -y ffmpeg python3-venv
python3 -m venv venv && venv/bin/pip install -r requirements.txt
python3 -m venv asr-venv && asr-venv/bin/pip install -r bonus_asr/requirements-asr.txt
```

Choose the audio input with `AUDIO_INPUT` in `asr_source.py`:

```python
AUDIO_INPUT = ["-f", "pulse", "-i", "default"]     # default: system microphone
AUDIO_INPUT = ["-re", "-i", "lecture.wav"]         # audio or video file, played in real time
```

A VM usually has no microphone; use the file input there.

Run each command in its own terminal, in this order, from the repo root:

Terminal 1: caption server (same as the main project)
```bash
venv/bin/python solution_server.py --port 8765
```

Terminal 2: web client (same as the main project)
```bash
python3 -m http.server 8000 -d client      # open http://127.0.0.1:8000
```

Terminal 3: ASR source
```bash
asr-venv/bin/python bonus_asr/asr_source.py
```

Press Ctrl+C once to stop the source: it skips any queued audio, sends the last caption as final, then sends `SOURCE_DONE`. Press Ctrl+C again to force quit.

**Restart the server before each run.**
