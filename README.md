# Team 12 - LiveRecall

## Team members

| Name | Student ID | Main responsibility |
|---|---|---|
| Aw Ming Xuan `@icyyolo` | A0308470H | Live-caption client UI (recall filters 15/30/60s, revision replacement, 90s pruning); client auto-reconnect with resume state & HISTORY merge; lag detection/exit tuning (idle-RTT baseline, soft-pong entry, shared-bottleneck exit, slow-reader pinning); bonus ASR source with draft/final revisions; public test runs & results |
| Kosolpattanadurong Thitiwat `@CATISNOTSODIUM` | A0305613N | Architecture & protocol design docs; history-window and disconnect-window optimisations (opt_server.py); client handling; utilities, Makefile, private test scripts & analytics; report writing and PDF generation |
| Lee Zhao Rui `@oilyfishball` | A0308380H | Starter-kit setup & docs organisation; per-connection send queues with unicast error handling, overflow drop & stale-packet removal; ping-based flow control, version control, disconnected-client handling; smart pacing & pipelining; results and AI usage declaration |
| Wong Ji Kean `@ji-just-ji` | A0252449Y | Caption store (store.py) and Source→Server update parsing with tests; batch-sending optimisation; data-structure optimisation moving work into store; send-timing/lag constant tuning; stress-testing harness (run_stress.py) | 


## Ubuntu setup
> All public tests below were run on **Ubuntu 26.04**.

On a fresh Ubuntu 26.04 machine (or VM):

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip iproute2
python3 --version   # check
tc -V               # check: tc/netem is needed for the network profiles
```

Run the server, the simulated clients and the network profiles all inside the same Ubuntu environment.

## Install

From the project root (the folder that contains `solution_server.py`):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt     # only dependency: websockets>=13,<17
```

The required path uses only `websockets`. `ffmpeg` and the ASR packages in `bonus_asr/requirements-asr.txt` are optional and are not needed for the server or the tests.

## Required server

```bash
source venv/bin/activate
python solution_server.py --port 8765
```

The server listens on `ws://127.0.0.1:8765` (the default port is 8765). To check the startup path and the required files:

```bash
python submission_check.py            # dev files + WebSocket handshake
python submission_check.py --final    # also checks README.md, AI_USAGE.md, CONTRIBUTIONS.md, report.pdf
```

## Browser client

1. Start the server on port 8765 as shown above. The client is hard-coded to `ws://127.0.0.1:8765` in `client/app.js`.
2. Start a caption source in a second terminal:
   ```bash
   source venv/bin/activate
   python caption_source.py --uri ws://127.0.0.1:8765 --session L1
   # or with your own text: --transcript sample_transcript.txt
   ```
3. Serve the client folder in a third terminal and open it in a browser:
   ```bash
   python3 -m http.server 8000 --directory client
   ```
   Then open <http://127.0.0.1:8000/>. Opening `client/index.html` directly with `file://` also works.
4. Open several tabs to see more than one viewer. To try late join, open a tab after captions have started. To try reconnect, stop and restart the tab's connection (or the network) and the client resumes from its last segment and revision.

If you run Ubuntu in a VM and the browser is on the host, either use a browser inside the VM or forward port 8765 (for example `ssh -L 8765:127.0.0.1:8765 -L 8000:127.0.0.1:8000`).

## Public deterministic tests

Unit test for the caption store (run from the parent folder of the project, because it imports `LiveRecall.server.store`):

```bash
cd ..
python -m LiveRecall.tests.test_store    # prints "ok"
cd LiveRecall
```

T1–T4. `run_demo.py` starts a new server for every run, uses a fixed seed (`--seed 3103` by default), and writes `<stem>.csv` / `<stem>.json`. Each test does 3 independent runs, and we report the median.

```bash
# T1 - basic correctness
python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem t1

# T2 - public scale
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2

# T3 - slow readers
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --slow-percent 10 --slow-ms 500 --output-stem t3

# T4 - reconnect
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
  --output-stem t4
```

The same tests through `make` (outputs go to `analytics/results/`):

```bash
make T1   # also T2, T3, T4
```

Optional memory trace during T3, in another terminal:

```bash
python monitor_server.py --match solution_server.py --duration 60 --output t3_memory.csv
```

### T5 - network impairment (Ubuntu, tc/netem on `lo`)

```bash
sudo ./network_profiles/delay_loss.sh lo
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5
sudo ./network_profiles/reset.sh lo      # always clear the impairment afterwards
```

The profiles available in `network_profiles/` are `bandwidth_2mbit`, `bandwidth_500kbit`, `delay_100ms`, `delay_loss`, `loss_3pct`, and `reorder`.

To run T1–T4 under each profile one after another (numbering the outputs from `t1`, and logging stem → profile in `test_profiles.txt`):

```bash
./run_public_tests.sh 1                       # none + all default profiles
./run_public_tests.sh 25 bandwidth_500kbit    # one specific profile
```

The script asks for `sudo` once and resets `lo` when it exits, even after a failure or Ctrl-C.

## Mandatory deterministic application demo

No ASR is needed. Run each command in its own terminal from the project root, with `venv` activated.

```bash
# Terminal 1 - server
python solution_server.py --port 8765

# Terminal 2 - browser client files
python3 -m http.server 8000 --directory client

# Terminal 3 - deterministic caption source (long mode so the 60 s recall view fills up)
python caption_source.py --uri ws://127.0.0.1:8765 --session L1 --duration 120
```

Open <http://127.0.0.1:8000/> in at least two tabs, then show:

1. **Provisional vs final.** Provisional captions are styled differently from finalized ones.
2. **Revision replacement.** Each segment appears once; newer revisions replace the text in place instead of appending a new line.
3. **Recall.** `What did I miss?` defaults to 30 s and switches between 15/30/60 s from local state, with no server request.
4. **Late join.** Open a new tab after captions have started; it receives recent finalized context through `HISTORY` and then continues live.
5. **Reconnect/recovery.** Restart the server connection for one tab (e.g. stop and restart `solution_server.py` while the source keeps running, or toggle the network). The client reconnects automatically with its `last_segment`/`last_revision` and recovers missed finals without duplicate finals.

## Design notes

The system has two parts: the solution server (`solution_server.py`) and the browser client (`client/app.js`). The server holds a `CaptionStore` (`server/store.py`) with the captions from the source, and one `Client` object per viewer with its WebSocket and send queue. The type of the first message on a connection (`SOURCE_HELLO` or `CLIENT_HELLO`) decides whether it goes to `handle_source` or `handle_client`.

### Revision/deduplication state

The store keeps a deque `order` of segment numbers and a map from segment number to an `Entry` (`source_ts`, revision, finality, text). Each `CAPTION_UPDATE` is parsed and validated (malformed messages are counted and dropped), then `store.apply(entry)` classifies it:

| Result | Condition | Action |
|---|---|---|
| `STALE` | Segment held and `new.revision <= cur.revision` | Drop; a delayed packet never rolls a caption back |
| `DUP_FINAL` | Segment already final (held as final, or at/below `contig_final`) | Drop; a final is never replaced |
| `TOO_OLD` | Older than the oldest segment still on the deque | Drop |
| `ACCEPTED` | Otherwise (re-sorted in the rare out-of-order case) | Replace entry, prune, broadcast |

`contig_final` is the highest N such that segments 1..N are all final. It lets the server reject late updates for finals it has already pruned from memory.

The client applies the same rule: a message updates its row only if `msg.revision > row.revision_id`, replacing the text in place; `is_final` is sticky, and rows are re-sorted by segment when updates arrive out of order. `HISTORY` items go through the same path, so overlap with live updates is deduplicated automatically.

### Bounded server history

On every accepted update, segments whose `source_ts` is older than `latest_ts - keep_seconds` (`keep_seconds = 120`) are pruned, and the deque is also capped at `max_items = 500` in case timestamps misbehave. The client keeps finals for `KEEP_MESSAGE_WINDOW = 90` s (above the required 60 s), pruning once a second; the 15/30/60 s recall view only hides rows, so changing it never asks the server for anything.

### Reconnect/late-join recovery

On reconnect (or late join, with `last_segment = 0`) the client sends `CLIENT_HELLO` with `last_segment`, `last_revision` and `history_seconds = 60`, under a stable `client_id` kept in `sessionStorage`. `get_history()` returns, in order, the finalized segments the client lacks within the last `history_seconds` (clamped to [0, 60]; invalid fields fall back to defaults). This `HISTORY` is queued before the client joins the broadcast set, so it always comes before live updates. A client the server cut off for being too slow (close code 1013) reconnects and recovers the same way; only a 1008 close (protocol violation, e.g. an invalid hello) is shown to the user instead of triggering a reconnect.

### Per-client buffering/backpressure

`broadcast(segment)` hands only the segment number to every client and returns at once without waiting on any send. Each client has a background sender, `unicast(client)`, that reads the segment's latest text from the store when it is ready to send. The sending path went through several versions; each one keeps everything before it, and the submitted `solution_server.py` is v6 (`LIVERECALL_VERSION` in `config.py` selects older versions for comparison).

| Version | What it does | Problem addressed |
|---|---|---|
| v0 Naive broadcast | Send each update to every client; the source awaits all sends. | Baseline: one slow client stalls the source and everyone else. |
| v1 Per-client dirty set | FIFO of segment ids per client; repeated edits keep their place and coalesce; text is read at send time. Close the client at 100 queued segments. | Backlog bounded by segments, not edits; slow readers block no one. |
| v2 Ping flow control | Ping after each send and wait for the pong (up to `PONG_WAIT` = 1 s). | `send()` returns once data is in the OS buffer, so the real backlog was invisible; pongs show the client actually read it. |
| v3 Lag-window disconnect | Disconnect a client whose oldest dirty entry is older than `MAX_LAG_WINDOW` = 10 s. | Bounds staleness; the client recovers via `HISTORY`. |
| v4 Lag mode | For slow clients: missing finals oldest first, newest provisional only after `LAG_PROV_GAP` = 4 s idle. | Finals never delayed; unreadable intermediate revisions skipped. |
| v5 Buffer-aware lag exit | Exit lag only when pongs are fast *and* the estimated receive buffer has drained. | Stops clients leaving lag with a full buffer and oscillating. |
| v6 Event-driven pacing | Lag-mode sender waits on an event from `broadcast()` instead of polling every 0.1 s; sends a new final at once even with a pong outstanding; pings every 2 messages (`PING_EVERY_N` = 2). | New finals go out immediately, and lag-mode throughput on high-latency links roughly doubles. |

**Receive-buffer estimate (v5+).** The server cannot see a client's receive buffer, so before letting a client leave lag mode it estimates the backlog conservatively:

1. Assume the buffer was full when lag began: `LAG_QUEUE_GUESS` = 32 messages.
2. Estimate the per-message read time `iv_est` from pong RTTs during lag, keeping the largest value seen (capped at `IV_CAP` = 1 s; initially the RTT of the pong that triggered lag, at least 0.1 s).
3. Estimated reads = time in lag / `iv_est`; the client must work through the 32 assumed messages plus everything sent during lag (`lag_sent`).
4. Exit once `reads - lag_sent >= LAG_QUEUE_GUESS + LAG_EXIT_MARGIN` (32 + 2) and the latest pong is fast (RTT <= 0.2 s). On exit, every in-progress segment is marked dirty again so the client gets its latest text right away.

### Overload behaviour and trade-offs

Each client's sender is a two-state machine:

- **Normal → Lag.** When the oldest unsent update is older than 0.5 s (`LAG_AGE_ENTER`), or a pong takes longer than 0.2 s (`LAG_PONG_SOFT`) or times out after 1 s. The dirty set is cleared; from then on the client gets missing finals oldest first (never paced) plus the latest provisional after 4 s without a send.
- **Lag → Normal.** When the latest pong is fast again and the receive-buffer estimate says the backlog has drained. In-progress segments are then re-queued.
- **Disconnect.** A client more than 10 s behind (or with 100 queued segments) is closed with 1013 and recovers its finals through `HISTORY`.

How this covers the two advanced challenges:

- **Slow-reader semantic backpressure.** Each backlog is bounded by the dirty set and the 10 s lag window, so it does not grow with the edit rate. Superseded provisionals are never queued, and `broadcast()` never waits, so a slow reader cannot delay the source or other clients.
- **Constrained-bandwidth semantic delivery.** On a congested link pongs come back slowly, which puts the client in lag mode. The remaining bandwidth goes to missing finals first and then the latest provisional, while intermediate revisions are skipped instead of building a stale backlog.

The trade-off: slow or bandwidth-limited clients see fewer intermediate provisional revisions and may be briefly disconnected, but finals are never lost or duplicated, and one bad client never affects the others. The conservative buffer estimate can also keep a recovered client in lag mode a little longer than needed; we accept that because underestimating would make it fall straight back into lag.

More detail is in `report.pdf`.

## Optional ASR bonus

`bonus_asr/asr_source.py` replaces `caption_source.py` as the caption source. It connects to the same `solution_server.py`, sends `SOURCE_HELLO`, then `CAPTION_UPDATE` messages, then `SOURCE_DONE`. **Neither `solution_server.py` nor the browser client was changed**, so revision semantics, history, backpressure, lag mode and recovery all apply to ASR captions. Its dependencies are kept out of `requirements.txt`.

### Pipeline

1. `ffmpeg` captures lecture audio or the mic (default) as 16 kHz mono s16le.
2. A reader thread cuts it into 1 s chunks in a bounded queue (30 chunks).
3. faster-whisper `base.en` transcribes on CPU (int8, 4 threads, VAD filter).
4. Results are sent as `CAPTION_UPDATE` to `solution_server.py`, and on to the browser client.

| Protocol field | How the ASR source sets it |
|---|---|
| `segment` | One segment per fixed 5 s window (`SEGMENT_TIMING_SEC = 5`); only incremented if the window produced text, so silence creates no empty segments. |
| `revision` | Each new 1 s chunk re-transcribes the whole window so far and sends it as the next revision. The first waits for 2 s of audio (`FIRST_REVISION_SEC = 2`), giving up to 3 provisional revisions and 1 final per segment. |
| `final` | `true` once the window reaches 5 s, and for the partial window flushed on shutdown. |
| `text` | The full transcript of the window (not a delta), so replace-by-revision shows the newest hypothesis even when Whisper rewrites earlier words. |
| `source_ts` | Wall-clock time the newest audio chunk was read. |

### How to run it

```bash
sudo apt install -y ffmpeg
python3 -m venv asr-venv
asr-venv/bin/pip install -r bonus_asr/requirements-asr.txt
```

From the repository root, one terminal each, in this order:

```bash
venv/bin/python solution_server.py --port 8765
python3 -m http.server 8000 -d client      # open http://127.0.0.1:8000
asr-venv/bin/python bonus_asr/asr_source.py
```

The first run downloads the `base.en` model (about 150 MB). To change the audio input, edit `AUDIO_INPUT` in `asr_source.py` (e.g. `["-f", "pulse", "-i", "RDPSource"]`). **Restart the server and reload the browser before each ASR run** (see limitations).

### Limitations

- **Fixed-time segmentation.** Windows end every 5 s regardless of speech, so sentences (and sometimes words) are split, and each window is transcribed without the previous one as context. Pause-based segmentation using the VAD would fix this.
- **Re-transcription cost.** Each revision re-transcribes 2-5 s of audio; if that takes longer than the 1 s chunk interval, audio queues up.
- **Overload drops audio.** When transcription falls behind, the oldest queued chunk is dropped and logged, capping caption delay at about 30 s at the cost of lost words.
- **No source reconnect or session reset.** Segment numbers restart at 1 every run, but the server rejects updates for segments it already holds as final and the browser ignores lower revisions, so the server and browser must be restarted. The source also does not reconnect if the connection drops.
- **Clock assumption.** `source_ts` uses the source machine's clock and the recall window compares it with the browser's, which holds when both run on the same machine.
- **Accuracy not tuned.** `base.en` on CPU was picked for real-time speed; accuracy and model size are not graded.
