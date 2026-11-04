#!/usr/bin/env bash
# Public tests T1-T5 (docs/PUBLIC_TESTS.md), 3 runs each.
# Usage: [OUT=DIR] [SERVER=FILE] ./run_public_tests.sh
#   SERVER defaults to solution_server.py, OUT to tests/test_results/public/v6 (files overwritten).
#   T5 impairs lo with delay_loss (needs sudo); lo is always reset afterwards.
set -euo pipefail
cd "$(dirname "$0")"
OUT=${OUT:-tests/test_results/public/v6}
mkdir -p "$OUT"
SERVER=${SERVER:-solution_server.py}

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
