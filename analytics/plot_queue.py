"""Plot average and max client queue length from a server log.

Parses [PROFILE_QUEUE_LENGTH] lines emitted by solution_server.print_queue():
    [PROFILE_QUEUE_LENGTH] average <monotonic_ts> <avg_len> max <max_len>
and, for V3 servers, the cumulative lag-window drop counter:
    [PROFILE_LAG_DROPS] <monotonic_ts> <drops>

Usage: python plot_queue.py [LOG] [OUT]
"""
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PATTERN = re.compile(
    r"^\[PROFILE_QUEUE_LENGTH\] average (\S+) (\S+) max (\S+)$"
)
DROPS_PATTERN = re.compile(r"^\[PROFILE_LAG_DROPS\] (\S+) (\S+)$")


def parse(log_path: Path):
    ts, avg, mx = [], [], []
    drop_ts, drops = [], []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            m = PATTERN.match(line)
            if m:
                ts.append(float(m.group(1)))
                avg.append(float(m.group(2)))
                mx.append(int(m.group(3)))
                continue
            m = DROPS_PATTERN.match(line)
            if m:
                drop_ts.append(float(m.group(1)))
                drops.append(int(m.group(2)))
    if not ts:
        raise SystemExit(f"No [PROFILE_QUEUE_LENGTH] lines found in {log_path}")
    t0 = ts[0]
    return [t - t0 for t in ts], avg, mx, [t - t0 for t in drop_ts], drops


def style(ax):
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")
    ax.tick_params(colors="#555")


def plot(t, avg, mx, drop_t, drops, title: str, out: Path):
    if drops:
        # Separate panel rather than a second y-axis: different units
        fig, (ax, dax) = plt.subplots(
            2, 1, figsize=(10, 7), dpi=150, sharex=True,
            gridspec_kw={"height_ratios": [3, 1.3]},
        )
    else:
        fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.plot(t, mx, color="#eb6834", linewidth=2, label="Max queue length")
    ax.plot(t, avg, color="#2a78d6", linewidth=2, label="Average queue length")

    ax.set_title(title, loc="left", fontsize=13, color="#1a1a19", pad=28)
    ax.set_ylabel("Queue length (messages)", color="#555")
    style(ax)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2)

    # Direct-label the peak of each series
    for series, color, name in ((mx, "#eb6834", "max"), (avg, "#2a78d6", "avg")):
        i = max(range(len(series)), key=series.__getitem__)
        ax.annotate(
            f"peak {name} = {round(series[i], 1):g}",
            (t[i], series[i]),
            xytext=(6, 6), textcoords="offset points",
            fontsize=9, color="#333",
        )
        ax.plot(t[i], series[i], "o", color=color, markersize=6,
                markeredgecolor="white", markeredgewidth=1.5)

    if drops:
        dax.step(drop_t, drops, where="post", color="#2a78d6", linewidth=2)
        dax.set_ylabel("Lag-window drops\n(cumulative)", color="#555")
        style(dax)
        dax.set_ylim(top=max(1, max(drops)) * 1.15)
        # Counter restarts with each server run; sum each run's final value
        total = drops[-1] + sum(a for a, b in zip(drops, drops[1:]) if b < a)
        dax.annotate(
            f"total = {total}", (drop_t[-1], drops[-1]),
            xytext=(-6, 6), textcoords="offset points", ha="right",
            fontsize=9, color="#333",
        )
    (dax if drops else ax).set_xlabel("Time since first sample (s)", color="#555")

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"Saved {out} ({len(t)} samples)")


def main():
    log = Path(sys.argv[1] if len(sys.argv) > 1 else "slow_disconnect.log")
    default_out = Path(__file__).resolve().parent / "figures" / f"{log.stem}_queue_length.png"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else default_out
    t, avg, mx, drop_t, drops = parse(log)
    plot(t, avg, mx, drop_t, drops, f"Client queue length — {log.stem}", out)


if __name__ == "__main__":
    main()
