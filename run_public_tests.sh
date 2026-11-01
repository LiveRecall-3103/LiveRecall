#!/usr/bin/env bash
# Run public tests T1-T4, numbering outputs from START.
# Usage: ./run_public_tests.sh START   e.g. START=9 -> t9_*, t10_*, t11_*, t12_*
set -euo pipefail
cd "$(dirname "$0")"

n=${1:?usage: $0 START_NUMBER}
[[ $n =~ ^[0-9]+$ ]] || { echo "START_NUMBER must be a non-negative integer" >&2; exit 1; }

python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem "t$n"
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem "t$((n+1))"
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --slow-percent 10 --slow-ms 500 --output-stem "t$((n+2))"
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
  --output-stem "t$((n+3))"
