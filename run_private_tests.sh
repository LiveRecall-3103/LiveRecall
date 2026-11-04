#!/usr/bin/env bash
# Harder-than-public tests aimed at what the hidden evaluator may vary (spec section 10).
# Usage: [OUT=DIR] [SERVER=FILE] ./run_private_tests.sh START [TEST...]
#   Runs SERVER (default "solution_server copy.py"). Results go to OUT, a path relative to the repo
#   (default tests/test_results/Private/v5);
#   same-named files there are overwritten.
#   TEST = delay delay_loss slow30 slow50_500ms bw300 recover reconnect scale300 scale500 fast combo
# Limits follow the instructor's clarification: a segment arrives every 0.75 s with 3 revisions, so
# slow readers sit between 250 ms (all revisions) and 750 ms (finals only) per message, and bandwidth
# carries finals but not every revision (300 clients: finals ~1.1 Mbit/s, full stream ~3.1 Mbit/s).
# Every test must allow 100% final completeness. The client library holds ~16 unread messages before
# any server can see a slow reader, so slow-ms stays <= 500: a 500 ms reader has ~20 reads to spare
# in 60 s after that backlog, a 600 ms reader only ~4.
#   default: all of them (~30 min). e.g. START=1 -> delay: p1, delay_loss: p2, ...
# Each test runs 3 times (OUT/p<N>_run01..03.{csv,json}), samples server memory into
# OUT/p<N>_run0X_rss.csv, prints medians, and saves its full output (including the server's
# "lag entries" line) to OUT/p<N>.log. The stem -> test mapping is appended to private_profiles.txt.
# Ends with a rough rubric-based mark estimate, also saved to OUT/grade.txt
# (grade_private.py; re-run it any time to re-grade).
set -euo pipefail
cd "$(dirname "$0")"
OUT=${OUT:-tests/test_results/Private/v5}
mkdir -p "$OUT"
SERVER=${SERVER:-solution_server copy.py}

ALL="delay delay_loss slow30 slow50_500ms bw300 recover reconnect scale300 scale500 fast combo"
n=${1:?usage: $0 START_NUMBER [TEST...]}
[[ $n =~ ^[0-9]+$ ]] || { echo "START_NUMBER must be a non-negative integer" >&2; exit 1; }
shift
tests=(${@:-$ALL})
for t in "${tests[@]}"; do
  [[ " $ALL " == *" $t "* ]] || { echo "unknown test: $t (choose from: $ALL)" >&2; exit 1; }
done

net() {  # apply a network condition to lo: none or a network_profiles/ script
  case $1 in
    none) ./network_profiles/reset.sh lo ;;
    *) "./network_profiles/$1.sh" lo ;;
  esac
}

demo() {  # OUT ARGS...: one run_demo.py run
  local out=$1; shift
  python run_demo.py --server "$SERVER" --runs 1 --output-stem "$out" "$@"
}

recover() {  # OUT ARGS...: like demo, but the 2 Mbit limit is on only from ~15 s to ~40 s
  ( sleep 15; net bandwidth_2mbit; sleep 25; net none ) &
  local timer=$!
  demo "$@"
  wait "$timer"
}

fast() {  # OUT CLIENTS DURATION: like demo, but captions 4x faster; run_demo.py can't set the rate
  local out=$1 clients=$2 duration=$3
  local segs=$(( (duration - 3) * 5 ))    # 0.2 s per segment: 2 x 0.05 revision delay + 0.1 gap
  python -u "$SERVER" --port 8765 &
  local srv=$!
  until (exec 3<>/dev/tcp/127.0.0.1/8765) 2>/dev/null; do kill -0 "$srv"; sleep 0.2; done
  python -u load_clients.py --clients "$clients" --duration "$duration" --output "$out.csv" &
  local cl=$!
  sleep 1
  python -u caption_source.py --segments "$segs" --revision-delay 0.05 --segment-gap 0.1 --quiet
  wait "$cl"
  kill "$srv"; wait "$srv" || true
  python analyse_results.py "$out.csv" --expected-finals "$segs" \
    --expected-updates $((segs * 3)) --json-output "$out.json"
}

runs() {  # STEM CMD ARGS...: runs `CMD STEM_run0R ARGS...` 3 times with memory sampling, then medians
  local stem=$1 cmd=$2; shift 2
  for r in 1 2 3; do
    local out="${stem}_run0$r"
    # CMD (re)starts the server, so the sampler waits a moment, then follows it until it exits.
    ( sleep 1; python monitor_server.py --match "$SERVER --port 8765" \
        --duration 600 --output "${out}_rss.csv" > /dev/null ) &
    local mon=$!
    "$cmd" "$out" "$@"
    wait "$mon" || true
    if [[ -f ${out}_rss.csv ]]; then
      awk -F, 'NR==2 {s=$2} NR>1 {e=$2; if ($2 > m) m=$2}
        END {printf "Server RSS: start %.1f MB, end %.1f MB, peak %.1f MB\n", s, e, m}' "${out}_rss.csv"
    fi
  done
  python -c 'import json, sys; from run_demo import print_medians
print_medians([json.load(open(f)) for f in sys.argv[1:]])' "${stem}"_run0?.json
}

sudo -v   # ask for the password once, up front
trap 'kill $(jobs -p) 2>/dev/null || true; ./network_profiles/reset.sh lo' EXIT   # never leave lo impaired

graded=()
for t in "${tests[@]}"; do
  stem="$OUT/p$n"
  graded+=("$t=$stem")
  echo "$stem: $t" | tee -a private_profiles.txt
  {   # a group (not a pipe) so background timers stay this shell's jobs and the trap can kill them
    case $t in
      delay)      net delay_100ms; runs "$stem" demo --clients 100 --duration 40 ;;
      delay_loss) net delay_loss;  runs "$stem" demo --clients 100 --duration 40 ;;
      slow30)     net none;        runs "$stem" demo --clients 100 --duration 60 --slow-percent 30 --slow-ms 500 ;;
      slow50_500ms) net none;      runs "$stem" demo --clients 100 --duration 60 --slow-percent 50 --slow-ms 500 ;;
      bw300)      net bandwidth_2mbit; runs "$stem" demo --clients 300 --duration 40 ;;
      recover)    net none;        runs "$stem" recover --clients 300 --duration 60 ;;
      reconnect)  net none;        runs "$stem" demo --clients 100 --duration 60 \
                                     --disconnect-percent 50 --disconnect-at 15 --disconnect-seconds 5 \
                                     --late-percent 20 --late-seconds 10 ;;
      scale300)   net none;        runs "$stem" demo --clients 300 --duration 40 ;;
      scale500)   net none;        runs "$stem" demo --clients 500 --duration 40 ;;
      fast)       net delay_100ms; runs "$stem" fast 100 40 ;;
      combo)      net delay_loss;  runs "$stem" demo --clients 300 --duration 60 --slow-percent 20 --slow-ms 500 ;;
    esac
  } > >(tee "$stem.log") 2>&1
  n=$((n+1))
done

python grade_private.py "${graded[@]}" | tee "$OUT/grade.txt"
