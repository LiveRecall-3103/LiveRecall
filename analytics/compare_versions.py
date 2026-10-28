"""Compare one public test across server versions (LIVERECALL_VERSION).

Reads what `make <TEST> V=<v>` writes into analytics/results/:
    <TEST>_v<v>_runNN.{csv,json}   (or <TEST>_v<v>.{csv,json} for --runs 1)
    <TEST>_v<v>.log                (server output incl. PROFILE lines)

Prints a median table and saves three figures to analytics/figures/:
    compare_<TEST>.png          one small panel per metric, a bar per version
    compare_<TEST>_tail.png     latency tail (CCDF) per client role, all runs pooled
    compare_<TEST>_queue.png    max queue length (+ lag drops on V3+) over time

Usage: python compare_versions.py TEST VERSION [VERSION ...]
       e.g. python compare_versions.py T3 2 3
"""
import csv
import json
import math
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plot_queue import parse, style

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
FIGURES = HERE / "figures"
FRESH_MS = 500.0  # run_demo.py --fresh-threshold-ms default

# (label, summary path, unit): run_demo.py's median metrics, plus per-role,
# recovery and correctness counters from the same summary JSON
METRICS = [
    ("P50 caption age", "p50_ms", "ms"),
    ("P95 caption age", "p95_ms", "ms"),
    ("P99 caption age", "p99_ms", "ms"),
    ("Normal-client P50", "normal_clients.p50_ms", "ms"),
    ("Normal-client P95", "normal_clients.p95_ms", "ms"),
    ("Slow-client P50", "slow_clients.p50_ms", "ms"),
    ("Slow-client P95", "slow_clients.p95_ms", "ms"),
    ("Fresh caption ratio", "fresh_pct", "%"),
    ("Fresh final ratio", "fresh_final_pct", "%"),
    ("Normal-client fresh", "normal_clients.fresh_pct", "%"),
    ("Slow-client fresh", "slow_clients.fresh_pct", "%"),
    ("Final completeness", "final_completeness_pct", "%"),
    ("Normal update coverage", "normal_update_coverage_pct", "%"),
    ("Recovery P50", "recovery_p50_ms", "ms"),
    ("Recovery P95", "recovery_p95_ms", "ms"),
    ("Reconnections", "reconnections", "count"),
    ("Stale + duplicate", "stale_or_duplicate", "count"),
    ("Connection errors", "connection_errors", "count"),
]


def nested_value(d, path):
    # Same lookup as run_demo.nested_value, plus a few derived counters
    if path == "reconnections" and "connections" in d:
        return d["connections"] - d["clients"]
    if path == "stale_or_duplicate" and "stale" in d:
        return d["stale"] + d["duplicates"]
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur

# Categorical slots in fixed order; a version always gets the same colour
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
           "#e87ba4", "#008300", "#6250d6", "#e34948"]


def colour(version: str) -> str:
    return PALETTE[int(version) % len(PALETTE)]


def load_summaries(test: str, version: str) -> list[dict]:
    stem = f"{test}_v{version}"
    paths = sorted(RESULTS.glob(f"{stem}_run*.json")) or sorted(RESULTS.glob(f"{stem}.json"))
    if not paths:
        raise SystemExit(f"No results for {stem} in {RESULTS}/ - run: make {test} V={version}")
    return [json.loads(p.read_text()) for p in paths]


def median_metric(summaries: list[dict], path: str):
    vals = [nested_value(s, path) for s in summaries]
    vals = [float(v) for v in vals if v is not None and not math.isnan(float(v))]
    return statistics.median(vals) if vals else None


def load_latencies(test: str, version: str) -> dict[str, list[float]]:
    """Accepted live caption ages from every run's CSV, split by client role.

    Same rows analyse_results.py uses for its P50/P95/P99.
    """
    stem = f"{test}_v{version}"
    paths = sorted(RESULTS.glob(f"{stem}_run*.csv")) or sorted(RESULTS.glob(f"{stem}.csv"))
    lat = {"All clients": [], "Normal clients": [], "Slow clients": []}
    for path in paths:
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r["event_type"] != "CAPTION_UPDATE" or r["status"] != "accepted"
                        or not r["latency_ms"]):
                    continue
                x = float(r["latency_ms"])
                lat["All clients"].append(x)
                lat["Slow clients" if r["slow"] == "1" else "Normal clients"].append(x)
    return lat


def total_drops(drops: list[int]) -> int:
    # Counter restarts with each server run; sum each run's final value
    if not drops:
        return 0
    return drops[-1] + sum(a for a, b in zip(drops, drops[1:]) if b < a)


def print_table(test, versions, medians, drops):
    print(f"\n=== {test}: median across runs ===")
    print(f"{'metric':26s}" + "".join(f"{'v' + v:>12s}" for v in versions))
    for label, _, unit in METRICS:
        row = [medians[v].get(label) for v in versions]
        if all(x is None for x in row):
            continue
        cells = "".join(f"{'-' if x is None else f'{x:.2f}':>12s}" for x in row)
        print(f"{label + ' (' + unit + ')':26s}{cells}")
    print(f"{'Lag-window drops':26s}" + "".join(
        f"{'-' if drops[v] is None else str(drops[v]):>12s}" for v in versions))


def plot_metrics(test, versions, medians, out: Path):
    shown = [(label, unit) for label, _, unit in METRICS
             if any(medians[v].get(label) is not None for v in versions)]
    cols = 4
    rows = math.ceil(len(shown) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(13, 2.5 * rows), dpi=150, squeeze=False)
    names = [f"v{v}" for v in versions]

    for ax, (label, unit) in zip(axes.flat, shown):
        vals = [medians[v].get(label) for v in versions]
        heights = [0 if x is None else x for x in vals]
        ax.bar(names, heights, width=0.55, color=[colour(v) for v in versions])
        for i, x in enumerate(vals):
            text = "n/a" if x is None else f"{x:.0f}" if unit == "count" else f"{x:.1f}"
            ax.annotate(text, (i, heights[i]),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8, color="#333")
        ax.set_title(f"{label} ({unit})", loc="left", fontsize=10, color="#1a1a19")
        style(ax)
        # style() pins x at 0, which clips categorical bars; leave room for labels
        ax.set_xlim(-0.6, len(versions) - 0.4)
        ax.set_ylim(top=(max(heights) or 1) * 1.2)
    for ax in list(axes.flat)[len(shown):]:
        ax.set_visible(False)

    fig.suptitle(f"{test}: median across runs by server version",
                 x=0.01, ha="left", fontsize=13, color="#1a1a19")
    fig.tight_layout()
    fig.savefig(out)
    print(f"Saved {out}")


def plot_tail(test, versions, latencies, out: Path):
    """Complementary CDF on log-log axes: the far right is the tail."""
    roles = [r for r in ("All clients", "Normal clients", "Slow clients")
             if any(latencies[v][r] for v in versions)]
    fig, axes = plt.subplots(1, len(roles), figsize=(4.4 * len(roles), 4.2), dpi=150,
                             sharey=True, squeeze=False)
    for ax, role in zip(axes.flat, roles):
        for v in versions:
            xs = sorted(latencies[v][role])
            if not xs:
                continue
            n = len(xs)
            # fraction of messages with age > x; drop the last point (0 on a log axis)
            ys = [(n - i - 1) / n for i in range(n)]
            ax.step(xs[:-1], ys[:-1], where="post", color=colour(v), linewidth=2,
                    label=f"v{v}")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.axvline(FRESH_MS, color="#8a8980", linewidth=1, linestyle="--")
        ax.annotate(f"fresh ≤ {FRESH_MS:g} ms", (FRESH_MS, 1), xytext=(4, -12),
                    textcoords="offset points", fontsize=8, color="#555")
        for p in (0.05, 0.01):  # P95 and P99 reference levels
            ax.axhline(p, color="#e5e4df", linewidth=0.8)
            ax.annotate(f"P{100 - round(p * 100)}", (1, p), xycoords=("axes fraction", "data"),
                        xytext=(-2, 2), textcoords="offset points", ha="right",
                        fontsize=8, color="#555")
        ax.set_title(role, loc="left", fontsize=11, color="#1a1a19")
        ax.set_xlabel("Caption age (ms, log)", color="#555")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c3c2b7")
        ax.tick_params(colors="#555")
    axes.flat[0].set_ylabel("Fraction of messages older than x (log)", color="#555")
    axes.flat[0].legend(frameon=False, loc="lower left")
    fig.suptitle(f"{test}: caption latency tail by server version",
                 x=0.01, ha="left", fontsize=13, color="#1a1a19")
    fig.tight_layout()
    fig.savefig(out)
    print(f"Saved {out}")


def plot_queues(test, versions, series, out: Path):
    has_drops = any(s["drops"] for s in series.values())
    if has_drops:
        # Separate panel rather than a second y-axis: different units
        fig, (ax, dax) = plt.subplots(
            2, 1, figsize=(10, 7), dpi=150, sharex=True,
            gridspec_kw={"height_ratios": [3, 1.3]},
        )
    else:
        fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    for v in versions:
        s = series[v]
        if s is None:
            continue
        ax.plot(s["t"], s["mx"], color=colour(v), linewidth=2, label=f"v{v}")
        if has_drops and s["drops"]:
            dax.step(s["drop_t"], s["drops"], where="post", color=colour(v),
                     linewidth=2, label=f"v{v}")

    ax.set_title(f"{test}: max client queue length by server version",
                 loc="left", fontsize=13, color="#1a1a19", pad=28)
    ax.set_ylabel("Max queue length (messages)", color="#555")
    style(ax)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.02),
              ncol=len(versions))
    if has_drops:
        dax.set_ylabel("Lag-window drops\n(cumulative)", color="#555")
        style(dax)
        top = max(max(s["drops"]) for s in series.values() if s and s["drops"])
        dax.set_ylim(top=max(1, top) * 1.15)
    (dax if has_drops else ax).set_xlabel("Time since first sample (s)", color="#555")

    fig.tight_layout()
    fig.savefig(out)
    print(f"Saved {out}")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    test, versions = sys.argv[1], sys.argv[2:]

    medians, drops, series, latencies = {}, {}, {}, {}
    for v in versions:
        summaries = load_summaries(test, v)
        medians[v] = {label: median_metric(summaries, path) for label, path, _ in METRICS}
        latencies[v] = load_latencies(test, v)
        log = RESULTS / f"{test}_v{v}.log"
        if log.exists():
            t, _, mx, drop_t, d = parse(log)
            series[v] = {"t": t, "mx": mx, "drop_t": drop_t, "drops": d}
            drops[v] = total_drops(d) if d else None
        else:
            series[v], drops[v] = None, None

    print_table(test, versions, medians, drops)
    FIGURES.mkdir(exist_ok=True)
    plot_metrics(test, versions, medians, FIGURES / f"compare_{test}.png")
    if any(latencies[v]["All clients"] for v in versions):
        plot_tail(test, versions, latencies, FIGURES / f"compare_{test}_tail.png")
    if any(series.values()):
        plot_queues(test, versions, series, FIGURES / f"compare_{test}_queue.png")


if __name__ == "__main__":
    main()
