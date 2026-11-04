#!/usr/bin/env python3
"""Rough estimate of the hidden-performance marks (spec 13.1) from run_private_tests.sh results.

NOT the real grader: the hidden thresholds are unknown, so every check scores linearly
between a guessed "bad" and "good" value. Use it to compare versions, not to predict a mark.

Usage: python grade_private.py [TEST=STEM ...]
  e.g. python grade_private.py delay=p1 slow30=p3
  default: the latest stem of each test listed in private_profiles.txt
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

from run_demo import nested_value

HERE = Path(__file__).resolve().parent
FRESH_MS = 500.0
LIMIT_OFF_S = 38.5   # source time when `recover` lifts the limit (~40 s after run_demo starts, source ~1.3 s later)
SETTLE_S = 3.0       # grace after the limit lifts before coverage must be back
# Instructor: hidden slow readers can always keep up with finals alone. The old slow50 test (now
# removed from run_private_tests.sh) read one message per 2 s while finals arrive every 0.75 s,
# so leftover slow50 results stay out of the gate.
BEYOND_FINAL_RATE = {"slow50"}
SLOW = ["slow30", "slow50_500ms"]


def lin(x, bad, good):
    """0 at `bad`, 1 at `good`, linear in between (works whichever direction is better)."""
    return max(0.0, min(1.0, (x - bad) / (good - bad)))


assert lin(0, 1, 0) == 1 and lin(99.5, 99, 100) == 0.5 and lin(5000, 2000, 200) == 0


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load(stem):
    return [{"summary": json.loads(p.read_text()), "csv": p.with_suffix(".csv"),
             "rss": p.with_name(p.stem + "_rss.csv")}
            for p in sorted(HERE.glob(f"{stem}_run0?.json"))]


def field(key):
    def get(run):
        v = nested_value(run["summary"], key)
        return None if v is None or math.isnan(float(v)) else float(v)
    return get


def slow_fresh_final(run):
    """Fresh Final Caption Ratio for slow clients only (analyse_results reports it for everyone)."""
    rows = read_rows(run["csv"])
    slow = {r["client_id"] for r in rows if r["slow"] == "1"}
    s = run["summary"]
    if not slow or not s.get("expected_finals_total"):
        return None
    first = {}
    for r in rows:
        if r["slow"] == "1" and r["final"] == "1" and r["status"] in ("accepted", "recovered") and r["latency_ms"]:
            key = (r["client_id"], r["segment"])
            first[key] = min(first.get(key, math.inf), float(r["latency_ms"]))
    per_client = s["expected_finals_total"] / s["clients"]
    return 100.0 * sum(v <= FRESH_MS for v in first.values()) / (per_client * len(slow))


def coverage_after_recovery(run):
    """Update coverage for segments that start after the bandwidth limit is lifted (+ settle time)."""
    rows = [r for r in read_rows(run["csv"])
            if r["event_type"] == "CAPTION_UPDATE" and r["status"] == "accepted"]
    seg_start = {}
    for r in rows:
        seg_start[r["segment"]] = min(seg_start.get(r["segment"], math.inf), float(r["source_ts"]))
    if not seg_start:
        return None
    t0 = min(seg_start.values())
    segs = {s for s, t in seg_start.items() if t - t0 >= LIMIT_OFF_S + SETTLE_S}
    got = {(r["client_id"], r["segment"], r["revision"]) for r in rows if r["segment"] in segs}
    # shortcut: assumes 3 revisions per segment, like run_demo.py's expected_updates
    return 100.0 * len(got) / (run["summary"]["clients"] * len(segs) * 3) if segs else None


def late_rss_growth(run):
    """MB the server grew after the first third of the run (connection setup excluded, backlog not)."""
    if not run["rss"].exists():
        return None
    mb = [float(r["rss_mb"]) for r in read_rows(run["rss"])]
    third = len(mb) // 3
    return max(mb[third:]) - mb[third] if len(mb) >= 3 else None


def latest_from_profiles():
    path = HERE / "private_profiles.txt"
    if not path.exists():
        sys.exit("No results: run ./run_private_tests.sh first, or pass TEST=STEM pairs.")
    latest = {}
    for line in path.read_text().splitlines():
        stem, _, name = line.partition(": ")
        if name:
            latest[name.strip()] = stem.strip()
    return [f"{n}={s}" for n, s in latest.items()]


def main():
    tests, stems = {}, {}
    for pair in sys.argv[1:] or latest_from_profiles():
        name, _, stem = pair.partition("=")
        runs = load(stem)
        if runs:
            tests[name], stems[name] = runs, stem
        else:
            print(f"(skipping {name}: no {stem}_run0?.json)")
    if not tests:
        sys.exit("No result files found.")

    def pick(names, per_run, worst=min):
        """Worst test, judged by each test's median across its runs."""
        meds = []
        for n in names:
            vals = [v for v in map(per_run, tests.get(n, [])) if v is not None]
            if vals:
                meds.append(statistics.median(vals))
        return worst(meds) if meds else None

    every = list(tests)

    def total_of(key):
        return sum(r["summary"].get(key, 0) for runs in tests.values() for r in runs)

    gated = [n for n in every if n not in BEYOND_FINAL_RATE]
    worst_completeness = pick(gated, field("final_completeness_pct"))

    # (rubric row, marks, check, value, bad, good, tests used)
    parts = [
        ("Correctness and invariants", 4, "worst final completeness %", worst_completeness, 99, 100,
         "all"),
        ("Correctness and invariants", 2, "stale + duplicate messages", total_of("stale") + total_of("duplicates"), 1, 0, "all"),
        ("Correctness and invariants", 1, "connection errors", total_of("connection_errors"), 1, 0, "all"),
        ("Correctness and invariants", 1, "server RSS growth after setup, MB",
         pick(every, late_rss_growth, max), 100, 20, "all"),
        # Spec: coverage is measured "during unconstrained operation", so impaired-network tests stay out.
        ("Normal coverage and freshness", 2, "update coverage % (no impairment)",
         pick(["scale300", "scale500"], field("normal_update_coverage_pct")), 90, 99.5,
         "scale300 scale500"),
        ("Normal coverage and freshness", 2, "fresh % (no impairment)",
         pick(["scale300", "scale500"], field("fresh_pct")), 90, 99, "scale300 scale500"),
        ("Delay/loss tail freshness", 1, "fresh % under delay/loss",
         pick(["delay", "delay_loss", "fast"], field("fresh_pct")), 80, 98, "delay delay_loss fast"),
        ("Delay/loss tail freshness", 1, "P95 under delay/loss, ms",
         pick(["delay", "delay_loss", "fast"], field("p95_ms"), max), 1000, 450, "delay delay_loss fast"),
        ("Slow-reader challenge", 3, "normal clients' fresh % beside slow readers",
         pick(SLOW, field("normal_clients.fresh_pct")), 85, 98, " ".join(SLOW)),
        # The rubric asks for "fresh useful state",
        # so fresh provisionals count as well as fresh finals.
        ("Slow-reader challenge", 1, "slow clients' fresh-final %",
         pick(SLOW, slow_fresh_final), 20, 80, " ".join(SLOW)),
        ("Slow-reader challenge", 1, "slow clients' fresh % (all updates)",
         pick(SLOW, field("slow_clients.fresh_pct")), 20, 80, " ".join(SLOW)),
        ("Slow-reader challenge", 1, "server RSS growth with slow readers, MB",
         pick(SLOW, late_rss_growth, max), 100, 20, " ".join(SLOW)),
        # Spec: "prioritize final captions and the latest useful state instead of building an
        # increasingly stale backlog" - so fresh finals, and what does arrive must be fresh.
        ("Constrained-bandwidth challenge", 3, "fresh-final % at 2 Mbit, 300 clients",
         pick(["bw300"], field("fresh_final_pct")), 30, 90, "bw300"),
        ("Constrained-bandwidth challenge", 3, "fresh % at 2 Mbit, 300 clients",
         pick(["bw300"], field("fresh_pct")), 80, 98, "bw300"),
        ("Reconnect and catch-up", 1, "recovery P95, ms",
         pick(["reconnect"], field("recovery_p95_ms"), max), 2000, 200, "reconnect"),
        # Spec 13.1 puts "rapid convergence ... after temporary outage/overload" in this row, not in
        # challenge 2, and section 10 wants full-update behavior back once the network catches up.
        ("Reconnect and catch-up", 1, "coverage % once the bandwidth limit lifts",
         pick(["recover"], coverage_after_recovery), 70, 98, "recover"),
        ("Reconnect and catch-up", 1, "final completeness % with reconnects",
         pick(["reconnect"], field("final_completeness_pct")), 99, 100, "reconnect"),
        ("Reconnect and catch-up", 1, "fresh % with reconnects",
         pick(["reconnect"], field("fresh_pct")), 90, 98, "reconnect"),
    ]
    assert sum(p[1] for p in parts) == 30, "rubric marks must add up to the 30 hidden-performance marks"

    print("\n=== Rough hidden-performance estimate (spec 13.1) ===")
    print("NOT the real grader: thresholds are guesses; each check scores linearly from 'bad' to 'good'.")
    print("Tests: " + ", ".join(f"{n}={stems[n]}" for n in every))
    got = avail = 0.0
    for row in dict.fromkeys(p[0] for p in parts):
        lines, row_got, row_avail = [], 0.0, 0
        for _, marks, check, value, bad, good, used in (p for p in parts if p[0] == row):
            if value is None:
                lines.append(f"      -  / {marks}  {check:44s} not run ({used})")
                continue
            score = marks * lin(value, bad, good)
            row_got, row_avail = row_got + score, row_avail + marks
            lines.append(f"    {score:4.1f} / {marks}  {check:44s} {value:9.2f}   (0 at {bad}, full at {good})")
        row_marks = sum(p[1] for p in parts if p[0] == row)
        head = f"{row_got:4.1f} / {row_avail}" + (f" of {row_marks} run" if row_avail < row_marks else "")
        print(f"\n{row:34s} {head}")
        print("\n".join(lines))
        got, avail = got + row_got, avail + row_avail

    scaled = 30 * got / avail
    wc = 100.0 if worst_completeness is None else worst_completeness
    cap = 5 if wc < 95 else 15 if wc < 99 else 30
    print(f"\nTotal: {got:.1f} / {avail:.0f} of the checks that ran"
          + (f"  ->  ~{scaled:.1f} / 30 if the rest scored the same" if avail < 30 else ""))
    print(f"Correctness gate: worst final completeness {wc:.2f}% -> "
          + ("no cap" if cap == 30 else f"capped at {cap}/30") + f"  =>  ~{min(scaled, cap):.1f} / 30")
    for n in BEYOND_FINAL_RATE & set(every):
        print(f"  ({n} not in the gate: its slow readers can't keep up with finals alone, "
              f"which the hidden tests won't do; its completeness was "
              f"{pick([n], field('final_completeness_pct')):.2f}%)")


if __name__ == "__main__":
    main()
