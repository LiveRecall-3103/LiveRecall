# LiveRecall

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

On macOS/Windows you can get an Ubuntu VM with Multipass:

```bash
multipass launch 26.04 --name liverecall --cpus 2 --memory 4G --disk 15G
multipass shell liverecall
```

Run the server, the simulated clients and the network profiles all inside the same Ubuntu environment.

## Install dependencies

From the project root (the folder that contains `solution_server.py`):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt     # only dependency: websockets>=13,<17
```

The required path uses only `websockets`. `ffmpeg` and the ASR packages in `bonus_asr/requirements-asr.txt` are optional and are not needed for the server or the tests.

## Start the server

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

If you run Ubuntu in a VM and the browser is on the host, either use a browser inside the VM or forward port 8765 (for example `multipass` port forwarding or `ssh -L 8765:127.0.0.1:8765 -L 8000:127.0.0.1:8000`).

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
