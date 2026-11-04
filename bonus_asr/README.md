# Optional Bonus: Real-Lecture ASR Integration

This folder is intentionally separate from the mandatory deterministic assignment path.

If your team attempts the bonus, connect a local/open-source ASR engine to the **same** LiveRecall protocol, `solution_server.py`, and browser client. Do not make ASR packages mandatory for `pip install -r requirements.txt` or for instructor performance evaluation.

Possible tools include faster-whisper, whisper.cpp, or Vosk. Speech-recognition accuracy/model size is not part of the mandatory networking score. Follow the assignment specification for the current bonus requirements.

## ASR source

`asr_source.py` captions audio with faster-whisper (`base.en`, CPU) while it plays and sends the captions as a normal LiveRecall source. `solution_server.py` and the browser client are unchanged.

System needs: ffmpeg and ffplay. The first run downloads the model (about 150 MB).

```bash
python3 -m venv asr-venv && asr-venv/bin/pip install -r bonus_asr/requirements-asr.txt
```

Set the input in `asr_source.py` to use the mic:

```python
AUDIO_INPUT = ["-f", "pulse", "-i", "RDPSource"] 
```

Run each command in its own terminal, from the repo root:

```bash
venv/bin/python solution_server.py --port 8765
python3 -m http.server 8000 -d client      # open http://127.0.0.1:8000
asr-venv/bin/python bonus_asr/asr_source.py
```

Restart the server before each run.
