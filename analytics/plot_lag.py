"""Plot the number of clients in lag mode over time from a server log.

Parses [PROFILE_LAG] lines emitted by solution_server.print_queue() (every 1 s):
    [PROFILE_LAG] <monotonic_ts> lagging <n> entries <E> exits <X> [clients <C>]
(`clients` is optional so older logs still parse.)

Outputs a PNG plot plus a CSV of the series, and prints a summary.

Usage: python analytics/plot_lag.py [LOG] [OUT_PNG]
   eg: python solution_server.py | tee server.log   # run the test, then:
       python analytics/plot_lag.py server.log analytics/figures/lag.png
"""
import csv
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PATTERN = re.compile(
    r"^\[PROFILE_LAG\] (\S+) lagging (\d+) entries (\d+) exits (\d+)(?: clients (\d+))?"
)


def parse(log_path: Path):
    rows = []
    with log_path.open(errors="ignore") as f:
        for line in f:
            m = PATTERN.match(line.strip())
            if m:
                ts, lag, ent, ex, cl = m.groups()
                rows.append((float(ts), int(lag), int(ent), int(ex),
                             int(cl) if cl is not None else None))
    if not rows:
        raise SystemExit(f"No [PROFILE_LAG] lines found in {log_path}")
    t0 = rows[0][0]
    return [(t - t0, *rest) for t, *rest in rows]


def summarize(rows) -> None:
    lag = [r[1] for r in rows]
    dur = rows[-1][0] or 1.0
    # time-weighted: each sample stands for the interval until the next one
    weighted = sum(rows[i][1] * (rows[i + 1][0] - rows[i][0]) for i in range(len(rows) - 1))
    secs_with_lag = sum(rows[i + 1][0] - rows[i][0] for i in range(len(rows) - 1) if rows[i][1])
    print(f"samples            : {len(rows)} over {dur:.1f}s")
    print(f"peak lagging       : {max(lag)} (at t={rows[lag.index(max(lag))][0]:.1f}s)")
    print(f"mean lagging       : {weighted / dur:.2f}")
    print(f"time with >=1 lag  : {secs_with_lag:.1f}s ({100 * secs_with_lag / dur:.0f}%)")
    print(f"lag entries/exits  : {rows[-1][2]} / {rows[-1][3]}")
    if rows[-1][4] is not None:
        print(f"clients at end     : {rows[-1][4]}")


def plot(rows, out: Path) -> None:
    t = [r[0] for r in rows]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    if rows[0][4] is not None:
        ax1.step(t, [r[4] for r in rows], where="post", color="#b9b7ad",
                 linewidth=1.2, label="connected clients")
    ax1.step(t, [r[1] for r in rows], where="post", color="#d1495b",
             linewidth=1.8, label="clients in lag mode")
    ax1.set_ylabel("clients")
    ax1.set_title("Slow clients (lag mode) over time")
    ax1.legend(frameon=False, loc="upper left")

    ax2.plot(t, [r[2] for r in rows], color="#2e6f9e", label="lag entries (cum.)")
    ax2.plot(t, [r[3] for r in rows], color="#3c9d5d", label="lag exits (cum.)")
    ax2.set_ylabel("count")
    ax2.set_xlabel("time since first sample (s)")
    ax2.legend(frameon=False, loc="upper left")

    for ax in (ax1, ax2):
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"plot               : {out}")


def main() -> None:
    log = Path(sys.argv[1] if len(sys.argv) > 1 else "server.log")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "analytics/figures/lag_clients.png")
    rows = parse(log)
    csv_out = out.with_suffix(".csv")
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "lagging", "lag_entries", "lag_exits", "clients"])
        w.writerows(rows)
    summarize(rows)
    print(f"csv                : {csv_out}")
    plot(rows, out)


if __name__ == "__main__":
    main()
