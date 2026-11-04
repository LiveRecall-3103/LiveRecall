#!/usr/bin/env bash
# Run the public tests T1-T5 from docs/PUBLIC_TESTS.md, 3 runs each (run_demo.py restarts the
# server for every run; report the median).
# Usage: [OUT=DIR] [SERVER=FILE] [LIVERECALL_VERSION=N] ./run_public_tests.sh
#   Runs SERVER (default "solution_server copy.py" as v5). Results go to OUT/tN_run0X.{csv,json}, a path
#   relative to the repo (default tests/test_results/public/v5); same-named files there are overwritten.
#   For v6: SERVER=solution_server.py OUT=tests/test_results/public/v6 ./run_public_tests.sh
#   T5 applies the delay_loss profile to lo (needs sudo); impairment is always cleared afterwards.
set -euo pipefail
cd "$(dirname "$0")"
OUT=${OUT:-tests/test_results/public/v5}
mkdir -p "$OUT"
SERVER=${SERVER:-solution_server copy.py}
# "solution_server copy.py" reads its version from config.py, which defaults to 6; the v6 file ignores it.
export LIVERECALL_VERSION=${LIVERECALL_VERSION:-5}

demo() {  # STEM ARGS...: one test, 3 runs
  local stem=$1; shift
  python run_demo.py --server "$SERVER" --runs 3 --output-stem "$OUT/$stem" "$@"
}

sudo -v   # ask for the password once, up front
trap './network_profiles/reset.sh lo' EXIT   # always clear impairment, even on failure or Ctrl-C
./network_profiles/reset.sh lo               # T1-T4 run with no impairment

# T1 - Basic correctness
demo t1 --clients 20 --duration 20
# T2 - Public scale
demo t2 --clients 100 --duration 40
# T3 - Slow readers
demo t3 --clients 100 --duration 60 --slow-percent 10 --slow-ms 500
# T4 - Reconnect
demo t4 --clients 100 --duration 60 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5
# T5 - Network impairment
./network_profiles/delay_loss.sh lo
demo t5 --clients 100 --duration 40
