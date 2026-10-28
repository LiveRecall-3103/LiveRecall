#!/usr/bin/env python3
"""LiveRecall stress runner: a development proxy for the HIDDEN evaluation.

Put this file next to run_demo.py. It does NOT replace run_demo.py: your required
public results (T1-T5) must still come from the unmodified run_demo.py.

Same flow as run_demo.py (fresh server per run, load_clients.py, analyse_results.py
untouched) plus the dimensions the hidden evaluator may vary:

  population        --clients N
  delay/jitter/loss --delay-ms --jitter-ms --loss-pct   (Linux tc/netem on lo, needs sudo)
  bandwidth         --rate-kbit                          (netem rate limit on lo)
  slow readers      --slow-percent --slow-ms
  disconnects       --disconnect-percent --disconnect-at --disconnect-seconds
  revision rate     --revisions --rev-delay --seg-gap
  burstiness        --burst-size --burst-gap --burst-delay
  temporary impairment (to see catch-up afterwards)  --impair-at --impair-for

Examples:
  python run_stress.py --list-presets
  python run_stress.py --preset slow --runs 3
  python run_stress.py --preset all --duration 40
  python run_stress.py --clients 300 --slow-percent 20 --loss-pct 1 --delay-ms 30
  sudo -v && python run_stress.py --preset bandwidth_cut_restore
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import websockets

from analyse_results import analyse_file, print_summary
from caption_source import DEFAULT_SENTENCES

HERE = Path(__file__).resolve().parent

# Named scenarios. Numbers are GUESSES at what a hidden workload might look like;
# tune them. Any flag you pass explicitly overrides the preset value.
PRESETS = {
    "baseline":        dict(clients=100),
    "scale":           dict(clients=400),
    "delay_jitter":    dict(clients=100, delay_ms=40, jitter_ms=20),
    "loss":            dict(clients=100, delay_ms=20, loss_pct=2.0),
    "slow":            dict(clients=100, slow_percent=20, slow_ms=1000),
    "slow_extreme":    dict(clients=100, slow_percent=40, slow_ms=3000),
    "reconnect_storm": dict(clients=200, disconnect_percent=50, disconnect_at=15, disconnect_seconds=8),
    "fast_revisions":  dict(clients=100, revisions=6, rev_delay=0.03, seg_gap=0.08),
    "bursty":          dict(clients=100, burst_size=25, burst_gap=4.0, burst_delay=0.0),
    "bandwidth":       dict(clients=100, rate_kbit=400, revisions=6, rev_delay=0.05, seg_gap=0.10),
    "bandwidth_cut_restore": dict(clients=100, rate_kbit=300, revisions=6, rev_delay=0.05,
                                  seg_gap=0.10, impair_at=15, impair_for=15, duration=60),
    "combined":        dict(clients=200, slow_percent=10, slow_ms=800, disconnect_percent=20,
                            disconnect_at=15, disconnect_seconds=5, delay_ms=20, jitter_ms=10,
                            loss_pct=0.5, burst_size=20, burst_gap=3.0, revisions=5,
                            rev_delay=0.05, seg_gap=0.15),
}

METRICS = [  # (label, key in analyse_results summary, unit)  -- same keys run_demo.py reports
    ("P50 caption age", "p50_ms", "ms"),
    ("P95 caption age", "p95_ms", "ms"),
    ("P99 caption age", "p99_ms", "ms"),
    ("Fresh Caption Ratio", "fresh_pct", "%"),
    ("Fresh Final Caption Ratio", "fresh_final_pct", "%"),
    ("Final completeness", "final_completeness_pct", "%"),
    ("Normal Update Coverage", "normal_update_coverage_pct", "%"),
    ("Normal-client P95", "normal_clients.p95_ms", "ms"),
    ("Slow-client P95", "slow_clients.p95_ms", "ms"),
    ("Recovery P95", "recovery_p95_ms", "ms"),
]


# ----------------------------------------------------------------- small helpers
def terminate_process(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def wait_for_port(port, proc, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("solution_server.py exited before becoming ready")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError("server did not listen within 10 seconds")


def nested_value(d, path):
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def median_of(summaries, path):
    vals = []
    for s in summaries:
        v = nested_value(s, path)
        try:
            if v is not None and not math.isnan(float(v)):
                vals.append(float(v))
        except (TypeError, ValueError):
            pass
    return statistics.median(vals) if vals else None


def raise_nofile(want=65536):
    """Many clients need many file descriptors; children inherit this limit (Linux)."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new = want if hard == resource.RLIM_INFINITY else min(want, hard)
        if soft < new:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new, hard))
        return resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except Exception:
        return None


# ------------------------------------------------------------------- tc / netem
DRY = False


def _tc(*a, check=True):
    cmd = ["tc", *a]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    if DRY:
        print("  [dry-netem] " + " ".join(cmd), flush=True)
        return
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("`tc` not found: install it with `sudo apt install -y iproute2` (Ubuntu only)")
    if check and r.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed: {r.stderr.strip()}  "
                           "(netem needs Ubuntu, iproute2 and sudo; try `sudo -v` first)")


def impairment_requested(a):
    return bool(a.delay_ms or a.loss_pct or a.rate_kbit)


def netem_apply(a):
    spec = ["qdisc", "replace", "dev", a.dev, "root", "netem"]
    if a.delay_ms:
        spec += ["delay", f"{a.delay_ms:g}ms"] + ([f"{a.jitter_ms:g}ms"] if a.jitter_ms else [])
    if a.loss_pct:
        spec += ["loss", f"{a.loss_pct:g}%"]
    if a.rate_kbit:
        spec += ["rate", f"{a.rate_kbit:g}kbit"]
    _tc(*spec)
    print(f"  netem ON  ({' '.join(spec[6:])}) on {a.dev}", flush=True)


def netem_clear(a):
    try:
        _tc("qdisc", "del", "dev", a.dev, "root", check=False)
        print(f"  netem OFF on {a.dev}", flush=True)
    except RuntimeError:
        pass                                                # tc missing: nothing was applied


# ------------------------------------------------------------- server memory log
class MemSampler(threading.Thread):
    """Samples the server's RSS from /proc (Linux). Boundedness is part of correctness."""

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.pid, self.stop_ev, self.samples = pid, threading.Event(), []

    def run(self):
        t0 = time.monotonic()
        while not self.stop_ev.is_set():
            try:
                with open(f"/proc/{self.pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            self.samples.append((time.monotonic() - t0, int(line.split()[1]) / 1024))
                            break
            except OSError:
                break
            self.stop_ev.wait(0.5)

    def report(self):
        if not self.samples:
            return {}
        mb = [m for _, m in self.samples]
        warm = [m for t, m in self.samples if t >= 5] or mb
        return {"rss_peak_mb": max(mb), "rss_end_mb": mb[-1], "rss_growth_mb": mb[-1] - warm[0]}


# ------------------------------------------------------------------ stress source
def make_revs(sentence, n):
    """n revisions of one sentence: growing prefixes, last one is the full text."""
    w = sentence.split()
    return [" ".join(w[:max(1, round(len(w) * k / n))]) for k in range(1, n)] + [sentence]


def seconds_per_segment(a):
    n = max(1, a.revisions)
    if a.burst_size > 0:
        return (a.burst_size * n * a.burst_delay + a.burst_gap) / a.burst_size
    return (n - 1) * a.rev_delay + a.seg_gap


def pick_segments(a):
    if a.source_segments:
        return a.source_segments
    active = max(3.0, a.duration - a.source_start_delay - 2.0)
    return max(4, math.floor(active / max(seconds_per_segment(a), 1e-3)))


async def source_main(uri, a, segments):
    """Same message format as caption_source.py, but with configurable rate/bursts."""
    pad = "x" * a.pad_bytes if a.pad_bytes else None
    bursting = a.burst_size > 0
    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "SOURCE_HELLO", "session": "L1"}))
        for seg in range(1, segments + 1):
            revs = make_revs(DEFAULT_SENTENCES[(seg - 1) % len(DEFAULT_SENTENCES)], a.revisions)
            rd = a.burst_delay if bursting else a.rev_delay
            for rev, text in enumerate(revs, start=1):
                e = {"type": "CAPTION_UPDATE", "session": "L1", "segment": seg, "revision": rev,
                     "source_ts": time.time(), "final": rev == len(revs), "text": text}
                if pad:
                    e["pad"] = pad                          # extra field: must be ignored by the server
                await ws.send(json.dumps(e))
                if rev < len(revs):
                    await asyncio.sleep(rd)
            if bursting and seg % a.burst_size == 0:
                await asyncio.sleep(a.burst_gap)
            else:
                await asyncio.sleep(a.burst_delay if bursting else a.seg_gap)
        await ws.send(json.dumps({"type": "SOURCE_DONE", "session": "L1",
                                  "source_ts": time.time(), "segments": segments}))


# ------------------------------------------------------------------------ one run
def one_run(a, name, run_no):
    outdir = Path(a.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    suffix = f"_run{run_no:02d}"
    csv_path, json_path = outdir / f"{name}{suffix}.csv", outdir / f"{name}{suffix}.json"
    uri = f"ws://127.0.0.1:{a.port}"
    segments = pick_segments(a)
    timed = impairment_requested(a) and a.impair_at is not None
    server = clients = sampler = None
    timers = []
    print(f"\n=== {name}: run {run_no}/{a.runs} ===")
    print(f"clients={a.clients} duration={a.duration}s segments={segments} x {a.revisions} revisions "
          f"| slow={a.slow_percent}%@{a.slow_ms}ms | disconnect={a.disconnect_percent}% "
          f"at {a.disconnect_at}s for {a.disconnect_seconds}s | burst={a.burst_size}/{a.burst_gap}s "
          f"| delay={a.delay_ms}+-{a.jitter_ms}ms loss={a.loss_pct}% rate={a.rate_kbit}kbit")
    try:
        server = subprocess.Popen(
            [sys.executable, "-u", "solution_server.py", "--port", str(a.port)], cwd=HERE,
            stdout=subprocess.DEVNULL if a.quiet_server else None,
            stderr=subprocess.STDOUT if a.quiet_server else None)
        wait_for_port(a.port, server)
        if not a.no_mem:
            sampler = MemSampler(server.pid)
            sampler.start()

        if impairment_requested(a) and not timed:
            netem_apply(a)                                  # whole run impaired

        clients = subprocess.Popen([
            sys.executable, "-u", "load_clients.py", "--uri", uri, "--clients", str(a.clients),
            "--duration", str(a.duration), "--output", str(csv_path.resolve()),
            "--history-seconds", str(a.history_seconds),
            "--slow-percent", str(a.slow_percent), "--slow-ms", str(a.slow_ms),
            "--disconnect-percent", str(a.disconnect_percent), "--disconnect-at", str(a.disconnect_at),
            "--disconnect-seconds", str(a.disconnect_seconds),
            "--late-percent", str(a.late_percent), "--late-seconds", str(a.late_seconds),
            "--seed", str(a.seed)], cwd=HERE)
        time.sleep(a.source_start_delay)
        if clients.poll() is not None:
            raise RuntimeError("load_clients.py exited early (too many clients for this machine/ulimit?)")

        if timed:                                           # impairment starts/stops mid-run
            def on():
                try:
                    netem_apply(a)
                except Exception as exc:
                    print(f"  !! could not apply netem: {exc}", flush=True)

            def off():
                netem_clear(a)
                print("  impairment removed: watch recovery P95 / how fast clients converge", flush=True)
            timers = [threading.Timer(a.impair_at, on), threading.Timer(a.impair_at + a.impair_for, off)]
            for t in timers:
                t.daemon = True
                t.start()

        t_src = time.time()
        asyncio.run(source_main(uri, a, segments))
        print(f"  source finished after {time.time() - t_src:.1f}s", flush=True)

        if clients.wait() != 0:
            raise RuntimeError("load_clients.py failed")
        summary = analyse_file(csv_path, expected_finals=segments,
                               expected_updates=segments * a.revisions,
                               fresh_threshold_ms=a.fresh_threshold_ms)
        print_summary(summary, a.fresh_threshold_ms)
        if sampler:
            sampler.stop_ev.set()
            mem = sampler.report()
            if mem:
                summary["server_memory"] = mem
                print(f"server RSS: peak {mem['rss_peak_mb']:.0f} MB, end {mem['rss_end_mb']:.0f} MB, "
                      f"growth since warm-up {mem['rss_growth_mb']:+.0f} MB")
        json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return summary
    finally:
        for t in timers:
            t.cancel()
        if impairment_requested(a):
            netem_clear(a)                                  # ALWAYS leave the loopback clean
        if sampler:
            sampler.stop_ev.set()
        terminate_process(clients)
        terminate_process(server)
        time.sleep(0.5)


# -------------------------------------------------------------------- CLI / main
def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", default="", help="name, comma list, or 'all' (see --list-presets)")
    p.add_argument("--list-presets", action="store_true")
    p.add_argument("--clients", type=int, default=100)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--output-dir", default="results/stress")
    p.add_argument("--seed", type=int, default=3103)
    p.add_argument("--history-seconds", type=int, default=30)
    p.add_argument("--fresh-threshold-ms", type=float, default=500.0)
    g = p.add_argument_group("client behaviour (passed to load_clients.py)")
    g.add_argument("--slow-percent", type=float, default=0)
    g.add_argument("--slow-ms", type=float, default=500)
    g.add_argument("--disconnect-percent", type=float, default=0)
    g.add_argument("--disconnect-at", type=float, default=10)
    g.add_argument("--disconnect-seconds", type=float, default=5)
    g.add_argument("--late-percent", type=float, default=0)
    g.add_argument("--late-seconds", type=float, default=5)
    s = p.add_argument_group("caption source shape")
    s.add_argument("--revisions", type=int, default=3, help="revisions per segment (public source uses 3)")
    s.add_argument("--rev-delay", type=float, default=0.20)
    s.add_argument("--seg-gap", type=float, default=0.35)
    s.add_argument("--burst-size", type=int, default=0, help="segments per burst; 0 = steady")
    s.add_argument("--burst-gap", type=float, default=3.0, help="idle seconds between bursts")
    s.add_argument("--burst-delay", type=float, default=0.0, help="delay between messages inside a burst")
    s.add_argument("--pad-bytes", type=int, default=0, help="extra field to enlarge messages (bandwidth tests)")
    s.add_argument("--source-segments", type=int)
    s.add_argument("--source-start-delay", type=float, default=1.0)
    n = p.add_argument_group("network impairment (Linux tc/netem, needs sudo)")
    n.add_argument("--delay-ms", type=float, default=0)
    n.add_argument("--jitter-ms", type=float, default=0)
    n.add_argument("--loss-pct", type=float, default=0)
    n.add_argument("--rate-kbit", type=float, default=0)
    n.add_argument("--dev", default="lo")
    n.add_argument("--impair-at", type=float, default=None,
                   help="apply impairment this many seconds after the source starts (default: whole run)")
    n.add_argument("--impair-for", type=float, default=15, help="how long a timed impairment lasts")
    n.add_argument("--dry-netem", action="store_true", help="print tc commands instead of running them")
    p.add_argument("--quiet-server", action="store_true")
    p.add_argument("--no-mem", action="store_true", help="skip server memory sampling")
    return p


def parse(argv, preset=None):
    p = build_parser()
    if preset:
        p.set_defaults(**PRESETS[preset])                   # explicit flags still win
    return p.parse_args(argv)


def main():
    global DRY
    argv = sys.argv[1:]
    pre = build_parser().parse_args(argv)
    if pre.list_presets:
        for k, v in PRESETS.items():
            print(f"{k:22s} {v}")
        return
    names = list(PRESETS) if pre.preset == "all" else [x for x in pre.preset.split(",") if x] or ["custom"]
    for n in names:
        if n != "custom" and n not in PRESETS:
            raise SystemExit(f"unknown preset {n!r}; try --list-presets")
    for f in ["solution_server.py", "load_clients.py", "caption_source.py", "analyse_results.py"]:
        if not (HERE / f).exists():
            raise SystemExit(f"Required file missing next to run_stress.py: {f}")

    lim = raise_nofile()
    DRY = pre.dry_netem
    if lim is not None and pre.clients * 2 + 200 > lim:
        print(f"warning: open-file limit is {lim}; run `ulimit -n 65536` before many clients")

    rows = []
    try:
        for name in names:
            a = parse(argv, None if name == "custom" else name)
            if a.duration <= 2:
                raise SystemExit("--duration should be > 2 seconds")
            summaries = [one_run(a, name, r) for r in range(1, a.runs + 1)]
            row = {"scenario": name, "runs": a.runs, "clients": a.clients}
            for label, key, unit in METRICS:
                row[key] = median_of(summaries, key)
            mems = [s.get("server_memory", {}).get("rss_peak_mb") for s in summaries]
            mems = [m for m in mems if m is not None]
            row["rss_peak_mb"] = max(mems) if mems else None
            rows.append(row)
    except KeyboardInterrupt:
        print("\ninterrupted; loopback impairment was cleared")
    except RuntimeError as e:
        raise SystemExit(str(e))

    if not rows:
        return
    print("\n=== Median per scenario ===")
    print(f"{'scenario':22s} {'clients':>7s} {'P95ms':>8s} {'P99ms':>8s} {'fresh%':>7s} "
          f"{'finals%':>8s} {'coverage%':>10s} {'RSSmax':>7s}  gate")
    def f(v, w, d=1):
        return f"{v:{w}.{d}f}" if v is not None else " " * (w - 1) + "-"
    for r in rows:
        comp = r["final_completeness_pct"]
        gate = "ok" if comp is None or comp >= 99 else ("CAP 15/30" if comp >= 95 else "CAP 5/30")
        print(f"{r['scenario']:22s} {r['clients']:7d} {f(r['p95_ms'],8)} {f(r['p99_ms'],8)} "
              f"{f(r['fresh_pct'],7)} {f(comp,8,2)} {f(r['normal_update_coverage_pct'],10)} "
              f"{f(r['rss_peak_mb'],7,0)}  {gate}")
    out = Path(pre.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "stress_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nPer-run CSV/JSON and stress_summary.csv are in {out}/")
    print("Reminder: final completeness below 99% caps hidden performance at 15/30; below 95% at 5/30.")


if __name__ == "__main__":
    main()