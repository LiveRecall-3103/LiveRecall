#!/usr/bin/env bash
# Run public tests T1-T4 once per network profile, numbering outputs from START.
# Usage: ./run_public_tests.sh START [PROFILE...]
#   PROFILE = "none" (no impairment) or a script name in network_profiles/
#   default: none bandwidth_2mbit delay_100ms delay_loss loss_3pct reorder
#   e.g. START=1 -> none: t1-t4, bandwidth_2mbit: t5-t8, ..., reorder: t21-t24
# The stem -> profile mapping is appended to test_profiles.txt.
set -euo pipefail
cd "$(dirname "$0")"

n=${1:?usage: $0 START_NUMBER [PROFILE...]}
[[ $n =~ ^[0-9]+$ ]] || { echo "START_NUMBER must be a non-negative integer" >&2; exit 1; }
shift
profiles=("${@:-none bandwidth_2mbit delay_100ms delay_loss loss_3pct reorder}")
profiles=(${profiles[*]})
for p in "${profiles[@]}"; do
  [[ $p == none || ( -f network_profiles/$p.sh && $p != reset ) ]] || { echo "unknown profile: $p" >&2; exit 1; }
done

sudo -v   # ask for the password once, up front
trap './network_profiles/reset.sh lo' EXIT   # always clear impairment, even on failure or Ctrl-C

for p in "${profiles[@]}"; do
  if [[ $p == none ]]; then ./network_profiles/reset.sh lo; else "./network_profiles/$p.sh" lo; fi
  echo "t$n-t$((n+3)): $p" | tee -a test_profiles.txt

  python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem "t$n"
  python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem "t$((n+1))"
  python run_demo.py --clients 100 --duration 60 --runs 3 \
    --slow-percent 10 --slow-ms 500 --output-stem "t$((n+2))"
  python run_demo.py --clients 100 --duration 60 --runs 3 \
    --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
    --output-stem "t$((n+3))"
  n=$((n+4))
done
