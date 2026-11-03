# LiveRecall Public Test Results

All 24 tests were run 3 times each (`run_demo.py --runs 3`, server restarted per run). The per-test tables list every v4 and v5 run (3 rows per version per test). The findings and the "P95 vs baseline" ratios use the median of the 3 runs. Raw per-run summaries are in `tN_run0X.json` / `.csv`.

## Test matrix

Each network profile runs the same four public scenarios (T1–T4) via `run_public_tests.sh` (mapping recorded in `test_profiles.txt`):

| Network profile | `tc` setting on `lo` | T1 Basic | T2 Scale | T3 Slow | T4 Reconnect |
|---|---|---|---|---|---|
| None (baseline) | – | t1 | t2 | t3 | t4 |
| bandwidth_2mbit | tbf rate 2mbit, burst 32kbit, latency 400ms | t5 | t6 | t7 | t8 |
| delay_100ms | netem delay 100ms ±20ms | t9 | t10 | t11 | t12 |
| delay_loss | netem delay 120ms ±30ms, loss 3% | t13 | t14 | t15 | t16 |
| loss_3pct | netem loss 3% | t17 | t18 | t19 | t20 |
| reorder | netem delay 20ms, reorder 20% 50% | t21 | t22 | t23 | t24 |

## Key findings

- **Correctness held in 71 of 72 runs.** 0 duplicates, 0 stale finals and 0 connection errors in every run. Final completeness is 100% everywhere except one run: t16 run 2 (delay_loss, T4) reached 99.34% (7,550 of 7,600 finals) in v4. The median is still 100%, and v5 reached 100% in all 72 runs.
- **Under latency or loss, only finals get through.** Each caption has 3 revisions, so an update coverage of 33.3% means only the final revision was delivered. That is what happens under delay_100ms (all tests), delay_loss (all tests) and bandwidth_2mbit at 100 clients (T2–T4). loss_3pct sits at 42–59%. Coverage stays at baseline (100%, or 94–98% in T3/T4) under no impairment and under reorder.
- **Skipping intermediates keeps finals fresh.** Fresh-final stays at ~98–100% under delay_100ms and bandwidth_2mbit, and is 85–93% under delay_loss.
- **delay_loss is still the worst profile.** P95 is 530–760 ms (79–310× baseline), fresh 85–93%, and reconnect recovery is ~250 ms (P50) / ~350 ms (P95).
- **Fixed delay shifts latency.** delay_100ms adds ~240–250 ms to P50 and reorder (20 ms) adds ~40 ms. That is roughly twice the netem value, because a caption crosses `lo` twice (source → server → client).
- **Loss mostly hits the tail.** loss_3pct leaves T1 P50 at baseline (1.2 ms), but P95 rises to ~90–210 ms (TCP retransmission timeout), and P50 rises to 20–34 ms at 100 clients.
- **Bandwidth matters only at scale.** At 20 clients 2 mbit is close to baseline (P95 3.4 ms). At 100 clients P95 rises to ~106–110 ms.
- **Slow readers (T3).** With no impairment and under reorder, normal clients stay at 100% fresh with baseline P95 (4.8 ms / 44.6 ms), while slow clients sit at ~2.3 s P50 / ~7.8 s P95 age and 35% fresh. The 94.3% fresh-final and coverage in those two rows come from the slow clients. Under bandwidth_2mbit, delay_100ms and delay_loss only finals are sent, so slow clients keep up and look the same as normal ones (92–100% fresh). Under loss_3pct, slow clients fall behind (P95 6.5 s, 62% fresh) while normal clients stay at 100% fresh.
- **Reconnect (T4)** recovery time follows the link latency: ≈2 ms baseline, 4 ms 2 mbit, 40 ms reorder, 200 ms delay_100ms, 250 ms delay_loss. Under loss_3pct it is 0.5 ms.

## Changes since the previous results

- delay_loss improved a lot: P95 ~1,000 ms → 530–760 ms, fresh-final ~18–31% → 85–93%, reconnect recovery P50 ~21 s → ~250 ms.
- Update coverage fell from ~96–100% to 33–59% under bandwidth_2mbit (100 clients), delay_100ms, delay_loss and loss_3pct (intermediate revisions are now skipped).
- loss_3pct P95 got worse: ~2–10 ms → ~90–210 ms.
- bandwidth_2mbit at 100 clients got worse: P95 ~42 ms → ~106–110 ms. Reconnect recovery improved: ~49 ms → ~4 ms.
- T3 baseline slow clients improved: P50 age ~4.2 s → ~2.3 s, fresh 5.9% → 35%, overall fresh-final 90.8% → 94.3%.

## v4 vs v5 (lag-mode wait change)

v4 = `tests/test_results/v4/`, v5 = `tests/test_results/v5/`. Same 24 tests, 3 runs each, same network profiles. Values are medians of the 3 runs (final completeness shows the worst run, since every median is 100%); latencies in ms.

The only server change is in `unicast()`: a lagging client used to poll for new captions every 0.1 s, and now it waits on `client.ready` and wakes the moment a caption arrives. Clients are marked lagging when their RTT is high, so the change only matters on impaired links.

- **Correctness unchanged or better.** v5 has 0 duplicates, 0 stale and 0 connection errors in all 72 runs, and 100% final completeness in every run (v4 t16 run 2 had 99.34%).
- **bandwidth_2mbit, 100 clients (t6–t8): ~3× faster.** P50 ~38–63 → 14–21 ms, P95 ~106–110 → 38–43 ms.
- **delay_100ms (t9–t12): ~47 ms faster at P50, ~70 ms at P95.** That matches the 0–100 ms (≈50 ms average) the old 0.1 s polling added.
- **delay_loss (t13–t16): P50 ~50 ms faster and fresh-final mostly up** (84.8 → 91.6% in t13, 81.0 → 86.9% in t16). The tail is mixed: t15 P95 got worse (533 → 687 ms) and t16 reconnect recovery P95 went from 339 → 584 ms (v5 runs vary 373–907 ms).
- **loss_3pct (t17–t20): P50 back near baseline** (20–34 → 3–4 ms at 100 clients), and P95 drops from ~91–96 → 3–8 ms in t17, t18 and t20. T3 slow-client P95 (~6.5 s) is unchanged.
- **No impairment (t1–t4) and reorder (t21–t24): no change.** Differences are within run-to-run noise, as expected, since no client is marked lagging there.

| Test | Scenario | Network | P50 v4 → v5 | P95 v4 → v5 | P99 v4 → v5 | Fresh-final % v4 → v5 | Final complete % (worst run) v4 → v5 | Coverage % v4 → v5 | Extra (v4 → v5) |
|---|---|---|---|---|---|---|---|---|---|
| t1 | T1 | None | 1.5 → 1.3 (-11%) | 2.4 → 2.0 (-18%) | 2.9 → 2.2 (-23%) | 100.0 → 100.0 | 100.00 → 100.00 | 100.0 → 100.0 |  |
| t2 | T2 | None | 3.6 → 3.5 (-4%) | 5.7 → 5.2 (-8%) | 8.4 → 5.7 (-32%) | 100.0 → 100.0 | 100.00 → 100.00 | 100.0 → 100.0 |  |
| t3 | T3 | None | 3.2 → 3.4 (+5%) | 6.8 → 5.5 (-18%) | 5,843 → 5,836 (-0%) | 94.3 → 94.3 | 100.00 → 100.00 | 94.3 → 94.3 | slow P50 2,252 → 2,253, slow P95 7,831 → 7,828 |
| t4 | T4 | None | 3.0 → 3.1 (+5%) | 4.8 → 5.1 (+6%) | 5.4 → 6.2 (+14%) | 98.4 → 98.4 | 100.00 → 100.00 | 98.2 → 98.2 | recovery P50 1.9 → 1.9, P95 2.1 → 2.0 |
| t5 | T1 | bandwidth_2mbit | 1.4 → 1.4 (+1%) | 3.4 → 3.5 (+3%) | 5.5 → 5.6 (+1%) | 100.0 → 100.0 | 100.00 → 100.00 | 100.0 → 100.0 |  |
| t6 | T2 | bandwidth_2mbit | 63.3 → 20.8 (-67%) | 109.7 → 43.3 (-60%) | 118.5 → 56.4 (-52%) | 100.0 → 100.0 | 100.00 → 100.00 | 33.3 → 33.3 |  |
| t7 | T3 | bandwidth_2mbit | 62.7 → 20.1 (-68%) | 108.3 → 38.9 (-64%) | 116.7 → 53.7 (-54%) | 100.0 → 100.0 | 100.00 → 100.00 | 33.3 → 33.3 | slow P50 60.8 → 29.6, slow P95 106.8 → 46.6 |
| t8 | T4 | bandwidth_2mbit | 38.2 → 14.0 (-63%) | 106.0 → 38.2 (-64%) | 114.7 → 52.5 (-54%) | 98.4 → 98.4 | 100.00 → 100.00 | 41.5 → 41.4 | recovery P50 4.2 → 7.9, P95 14.5 → 19.7 |
| t9 | T1 | delay_100ms | 242.1 → 195.7 (-19%) | 310.0 → 240.8 (-22%) | 334.1 → 262.4 (-21%) | 100.0 → 100.0 | 100.00 → 100.00 | 33.9 → 34.2 |  |
| t10 | T2 | delay_100ms | 249.1 → 201.8 (-19%) | 316.9 → 247.5 (-22%) | 338.6 → 265.2 (-22%) | 100.0 → 100.0 | 100.00 → 100.00 | 33.6 → 33.7 |  |
| t11 | T3 | delay_100ms | 253.1 → 203.7 (-20%) | 319.4 → 248.8 (-22%) | 340.5 → 267.8 (-21%) | 100.0 → 100.0 | 100.00 → 100.00 | 33.6 → 33.5 | slow P50 253.2 → 204.1, slow P95 319.4 → 251.2 |
| t12 | T4 | delay_100ms | 250.1 → 202.6 (-19%) | 316.3 → 249.2 (-21%) | 341.3 → 267.7 (-22%) | 98.2 → 98.2 | 100.00 → 100.00 | 32.9 → 32.9 | recovery P50 202.0 → 209.1, P95 249.5 → 239.7 |
| t13 | T1 | delay_loss | 300.3 → 254.0 (-15%) | 758.2 → 664.8 (-12%) | 832.9 → 728.7 (-13%) | 84.8 → 91.6 | 100.00 → 100.00 | 33.3 → 33.4 |  |
| t14 | T2 | delay_loss | 305.0 → 248.6 (-18%) | 635.2 → 648.9 (+2%) | 861.9 → 733.7 (-15%) | 88.7 → 91.9 | 100.00 → 100.00 | 33.4 → 33.4 |  |
| t15 | T3 | delay_loss | 301.5 → 253.0 (-16%) | 532.6 → 686.5 (+29%) | 726.0 → 892.0 (+23%) | 93.4 → 89.0 | 100.00 → 100.00 | 33.4 → 33.4 | slow P50 297.9 → 260.3, slow P95 558.3 → 727.7 |
| t16 | T4 | delay_loss | 302.2 → 252.2 (-17%) | 815.4 → 718.5 (-12%) | 1,085 → 1,036 (-5%) | 81.0 → 86.9 | 99.34 → 100.00 | 32.6 → 32.6 | recovery P50 251.3 → 240.0, P95 338.9 → 583.5 |
| t17 | T1 | loss_3pct | 1.2 → 1.3 (+6%) | 90.7 → 2.9 (-97%) | 228.4 → 14.1 (-94%) | 100.0 → 100.0 | 100.00 → 100.00 | 58.6 → 58.7 |  |
| t18 | T2 | loss_3pct | 19.9 → 3.1 (-84%) | 95.2 → 7.6 (-92%) | 241.4 → 216.5 (-10%) | 100.0 → 100.0 | 100.00 → 100.00 | 44.4 → 47.2 |  |
| t19 | T3 | loss_3pct | 34.2 → 3.5 (-90%) | 207.7 → 217.1 (+5%) | 4,893 → 4,831 (-1%) | 97.0 → 97.0 | 100.00 → 100.00 | 41.8 → 42.1 | slow P50 83.5 → 4.8, slow P95 6,494 → 6,593 |
| t20 | T4 | loss_3pct | 24.4 → 2.9 (-88%) | 96.4 → 5.4 (-94%) | 257.0 → 213.6 (-17%) | 98.4 → 98.6 | 100.00 → 100.00 | 42.5 → 42.5 | recovery P50 0.5 → 1.6, P95 0.8 → 1.7 |
| t21 | T1 | reorder | 41.4 → 41.4 (+0%) | 42.0 → 42.0 (+0%) | 42.2 → 42.2 (-0%) | 100.0 → 100.0 | 100.00 → 100.00 | 100.0 → 100.0 |  |
| t22 | T2 | reorder | 43.4 → 43.6 (+0%) | 44.9 → 45.3 (+1%) | 45.3 → 45.8 (+1%) | 100.0 → 100.0 | 100.00 → 100.00 | 100.0 → 100.0 |  |
| t23 | T3 | reorder | 43.2 → 43.5 (+1%) | 45.7 → 45.8 (+0%) | 5,876 → 5,879 (+0%) | 94.3 → 94.3 | 100.00 → 100.00 | 94.3 → 94.3 | slow P50 2,291 → 2,294, slow P95 7,865 → 7,871 |
| t24 | T4 | reorder | 42.9 → 43.3 (+1%) | 44.6 → 45.1 (+1%) | 45.2 → 45.7 (+1%) | 98.4 → 98.4 | 100.00 → 100.00 | 98.2 → 98.2 | recovery P50 40.3 → 40.3, P95 40.6 → 40.9 |

The per-test tables below list every v4 and v5 run (3 rows each per test).

## T1 Basic (20 clients, 20 s)

| Test | Network | Version | Run | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 | None | v4 | 1 | 1.4 | 2.1 | 2.5 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t1 | None | v4 | 2 | 1.5 | 2.4 | 2.9 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t1 | None | v4 | 3 | 1.5 | 2.5 | 3.0 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t1 | None | v5 | 1 | 1.5 | 2.3 | 2.5 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t1 | None | v5 | 2 | 1.3 | 1.8 | 2.0 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t1 | None | v5 | 3 | 1.3 | 2.0 | 2.2 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | bandwidth_2mbit | v4 | 1 | 1.4 | 3.4 | 5.5 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | bandwidth_2mbit | v4 | 2 | 1.4 | 3.2 | 5.1 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | bandwidth_2mbit | v4 | 3 | 1.2 | 4.0 | 5.8 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | bandwidth_2mbit | v5 | 1 | 1.4 | 3.5 | 6.1 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | bandwidth_2mbit | v5 | 2 | 1.4 | 3.4 | 5.1 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | bandwidth_2mbit | v5 | 3 | 1.3 | 3.7 | 5.6 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t9 | delay_100ms | v4 | 1 | 241.9 | 310.0 | 338.1 | 100.00 | 100.00 | 100.00 | 33.86 | 0 | 0 | 0 |
| t9 | delay_100ms | v4 | 2 | 248.4 | 310.3 | 334.1 | 100.00 | 100.00 | 100.00 | 34.02 | 0 | 0 | 0 |
| t9 | delay_100ms | v4 | 3 | 242.1 | 305.7 | 322.7 | 100.00 | 100.00 | 100.00 | 33.71 | 0 | 0 | 0 |
| t9 | delay_100ms | v5 | 1 | 192.9 | 236.1 | 248.2 | 100.00 | 100.00 | 100.00 | 34.24 | 0 | 0 | 0 |
| t9 | delay_100ms | v5 | 2 | 195.7 | 240.8 | 265.5 | 100.00 | 100.00 | 100.00 | 33.79 | 0 | 0 | 0 |
| t9 | delay_100ms | v5 | 3 | 201.2 | 247.3 | 262.4 | 100.00 | 100.00 | 100.00 | 34.24 | 0 | 0 | 0 |
| t13 | delay_loss | v4 | 1 | 300.3 | 758.2 | 832.9 | 81.59 | 81.59 | 100.00 | 33.33 | 0 | 0 | 0 |
| t13 | delay_loss | v4 | 2 | 316.6 | 828.4 | 974.1 | 84.81 | 84.77 | 100.00 | 33.41 | 0 | 0 | 0 |
| t13 | delay_loss | v4 | 3 | 296.3 | 740.8 | 832.2 | 90.68 | 90.68 | 100.00 | 33.33 | 0 | 0 | 0 |
| t13 | delay_loss | v5 | 1 | 248.1 | 629.2 | 699.4 | 92.76 | 92.73 | 100.00 | 33.48 | 0 | 0 | 0 |
| t13 | delay_loss | v5 | 2 | 261.0 | 707.5 | 872.9 | 82.09 | 82.05 | 100.00 | 33.41 | 0 | 0 | 0 |
| t13 | delay_loss | v5 | 3 | 254.0 | 664.8 | 728.7 | 91.59 | 91.59 | 100.00 | 33.33 | 0 | 0 | 0 |
| t17 | loss_3pct | v4 | 1 | 1.2 | 90.7 | 228.4 | 100.00 | 100.00 | 100.00 | 64.32 | 0 | 0 | 0 |
| t17 | loss_3pct | v4 | 2 | 1.2 | 88.0 | 99.7 | 100.00 | 100.00 | 100.00 | 57.88 | 0 | 0 | 0 |
| t17 | loss_3pct | v4 | 3 | 1.3 | 207.1 | 300.7 | 100.00 | 100.00 | 100.00 | 58.56 | 0 | 0 | 0 |
| t17 | loss_3pct | v5 | 1 | 1.2 | 2.0 | 2.5 | 100.00 | 100.00 | 100.00 | 58.71 | 0 | 0 | 0 |
| t17 | loss_3pct | v5 | 2 | 1.3 | 2.9 | 206.1 | 100.00 | 100.00 | 100.00 | 71.14 | 0 | 0 | 0 |
| t17 | loss_3pct | v5 | 3 | 1.5 | 3.5 | 14.1 | 100.00 | 100.00 | 100.00 | 53.41 | 0 | 0 | 0 |
| t21 | reorder | v4 | 1 | 41.3 | 41.7 | 42.0 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t21 | reorder | v4 | 2 | 41.4 | 42.1 | 42.8 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t21 | reorder | v4 | 3 | 41.5 | 42.0 | 42.2 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t21 | reorder | v5 | 1 | 41.4 | 42.0 | 42.2 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t21 | reorder | v5 | 2 | 41.4 | 41.9 | 42.1 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t21 | reorder | v5 | 3 | 41.4 | 42.1 | 42.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |

Median P95 vs no-impairment baseline (v4): bandwidth_2mbit 1×, delay_100ms 127×, delay_loss 310×, loss_3pct 37×, reorder 17×

Median P95 vs no-impairment baseline (v5): bandwidth_2mbit 2×, delay_100ms 121×, delay_loss 333×, loss_3pct 1×, reorder 21×

## T2 Scale (100 clients, 40 s)

| Test | Network | Version | Run | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t2 | None | v4 | 1 | 3.7 | 5.8 | 8.4 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t2 | None | v4 | 2 | 3.6 | 5.7 | 8.4 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t2 | None | v4 | 3 | 3.3 | 5.0 | 5.4 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t2 | None | v5 | 1 | 3.4 | 5.0 | 5.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t2 | None | v5 | 2 | 3.5 | 5.2 | 5.7 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t2 | None | v5 | 3 | 3.5 | 5.3 | 5.8 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t6 | bandwidth_2mbit | v4 | 1 | 63.3 | 110.0 | 119.8 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 |
| t6 | bandwidth_2mbit | v4 | 2 | 63.0 | 109.1 | 118.4 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 |
| t6 | bandwidth_2mbit | v4 | 3 | 63.5 | 109.7 | 118.5 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 |
| t6 | bandwidth_2mbit | v5 | 1 | 20.8 | 43.2 | 56.1 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 |
| t6 | bandwidth_2mbit | v5 | 2 | 20.7 | 43.8 | 56.4 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 |
| t6 | bandwidth_2mbit | v5 | 3 | 21.0 | 43.3 | 56.6 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 |
| t10 | delay_100ms | v4 | 1 | 249.1 | 311.8 | 333.4 | 100.00 | 100.00 | 100.00 | 33.61 | 0 | 0 | 0 |
| t10 | delay_100ms | v4 | 2 | 251.9 | 316.9 | 340.7 | 100.00 | 100.00 | 100.00 | 33.65 | 0 | 0 | 0 |
| t10 | delay_100ms | v4 | 3 | 246.9 | 317.8 | 338.6 | 100.00 | 100.00 | 100.00 | 33.60 | 0 | 0 | 0 |
| t10 | delay_100ms | v5 | 1 | 201.8 | 247.5 | 265.2 | 100.00 | 100.00 | 100.00 | 33.68 | 0 | 0 | 0 |
| t10 | delay_100ms | v5 | 2 | 208.5 | 255.2 | 274.6 | 100.00 | 100.00 | 100.00 | 33.59 | 0 | 0 | 0 |
| t10 | delay_100ms | v5 | 3 | 195.3 | 238.6 | 256.8 | 100.00 | 100.00 | 100.00 | 33.67 | 0 | 0 | 0 |
| t14 | delay_loss | v4 | 1 | 307.1 | 587.8 | 703.3 | 88.73 | 88.71 | 100.00 | 33.38 | 0 | 0 | 0 |
| t14 | delay_loss | v4 | 2 | 303.9 | 635.2 | 861.9 | 88.77 | 88.76 | 100.00 | 33.37 | 0 | 0 | 0 |
| t14 | delay_loss | v4 | 3 | 305.0 | 727.9 | 1066.3 | 88.37 | 88.37 | 100.00 | 33.34 | 0 | 0 | 0 |
| t14 | delay_loss | v5 | 1 | 248.6 | 648.9 | 733.7 | 91.96 | 91.94 | 100.00 | 33.41 | 0 | 0 | 0 |
| t14 | delay_loss | v5 | 2 | 252.5 | 747.7 | 983.6 | 86.73 | 86.67 | 100.00 | 33.33 | 0 | 0 | 0 |
| t14 | delay_loss | v5 | 3 | 246.9 | 540.4 | 724.5 | 93.05 | 93.04 | 100.00 | 33.36 | 0 | 0 | 0 |
| t18 | loss_3pct | v4 | 1 | 21.1 | 95.2 | 241.4 | 99.98 | 99.94 | 100.00 | 44.39 | 0 | 0 | 0 |
| t18 | loss_3pct | v4 | 2 | 19.9 | 91.6 | 99.1 | 99.98 | 99.98 | 100.00 | 44.27 | 0 | 0 | 0 |
| t18 | loss_3pct | v4 | 3 | 12.2 | 211.4 | 288.6 | 99.99 | 99.98 | 100.00 | 47.48 | 0 | 0 | 0 |
| t18 | loss_3pct | v5 | 1 | 3.1 | 7.6 | 213.4 | 99.97 | 99.96 | 100.00 | 47.16 | 0 | 0 | 0 |
| t18 | loss_3pct | v5 | 2 | 3.0 | 207.9 | 216.5 | 100.00 | 100.00 | 100.00 | 47.33 | 0 | 0 | 0 |
| t18 | loss_3pct | v5 | 3 | 3.1 | 6.1 | 234.0 | 100.00 | 100.00 | 100.00 | 46.82 | 0 | 0 | 0 |
| t22 | reorder | v4 | 1 | 43.3 | 44.8 | 45.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t22 | reorder | v4 | 2 | 43.4 | 44.9 | 45.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t22 | reorder | v4 | 3 | 43.4 | 45.2 | 46.5 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t22 | reorder | v5 | 1 | 43.7 | 45.3 | 45.8 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t22 | reorder | v5 | 2 | 43.6 | 45.3 | 47.2 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t22 | reorder | v5 | 3 | 43.4 | 44.9 | 45.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |

Median P95 vs no-impairment baseline (v4): bandwidth_2mbit 19×, delay_100ms 56×, delay_loss 112×, loss_3pct 17×, reorder 8×

Median P95 vs no-impairment baseline (v5): bandwidth_2mbit 8×, delay_100ms 47×, delay_loss 124×, loss_3pct 1×, reorder 9×

## T3 Slow readers (100 clients, 60 s, 10% slow @500 ms)

| Test | Network | Version | Run | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err | Slow P50 ms | Slow P95 ms | Slow fresh % | Normal P95 ms | Normal fresh % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t3 | None | v4 | 1 | 3.2 | 7.1 | 5845.4 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2252.0 | 7831.5 | 35.35 | 4.8 | 100.00 |
| t3 | None | v4 | 2 | 3.2 | 5.6 | 5839.3 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2253.0 | 7829.4 | 35.35 | 4.8 | 100.00 |
| t3 | None | v4 | 3 | 3.3 | 6.8 | 5843.2 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2251.7 | 7831.6 | 35.35 | 5.0 | 100.00 |
| t3 | None | v5 | 1 | 3.5 | 5.5 | 5836.4 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2252.8 | 7827.2 | 35.35 | 5.2 | 100.00 |
| t3 | None | v5 | 2 | 3.4 | 5.9 | 5834.2 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2252.0 | 7827.7 | 35.35 | 5.1 | 100.00 |
| t3 | None | v5 | 3 | 3.4 | 5.5 | 5837.7 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2253.8 | 7829.4 | 35.35 | 5.2 | 100.00 |
| t7 | bandwidth_2mbit | v4 | 1 | 62.5 | 108.3 | 116.8 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 | 60.7 | 106.8 | 100.00 | 108.3 | 100.00 |
| t7 | bandwidth_2mbit | v4 | 2 | 63.2 | 108.3 | 116.4 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 | 60.8 | 106.0 | 100.00 | 108.6 | 100.00 |
| t7 | bandwidth_2mbit | v4 | 3 | 62.7 | 108.5 | 116.7 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 | 61.8 | 107.0 | 100.00 | 108.7 | 100.00 |
| t7 | bandwidth_2mbit | v5 | 1 | 20.1 | 38.9 | 53.7 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 | 29.6 | 47.0 | 100.00 | 38.8 | 100.00 |
| t7 | bandwidth_2mbit | v5 | 2 | 20.3 | 38.9 | 53.8 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 | 29.5 | 46.6 | 100.00 | 38.8 | 100.00 |
| t7 | bandwidth_2mbit | v5 | 3 | 20.1 | 39.0 | 53.5 | 100.00 | 100.00 | 100.00 | 33.33 | 0 | 0 | 0 | 29.6 | 46.5 | 100.00 | 38.8 | 100.00 |
| t11 | delay_100ms | v4 | 1 | 253.1 | 319.6 | 341.8 | 99.93 | 99.95 | 100.00 | 33.59 | 0 | 0 | 0 | 254.4 | 319.4 | 99.35 | 319.6 | 100.00 |
| t11 | delay_100ms | v4 | 2 | 252.0 | 318.3 | 340.5 | 99.97 | 99.97 | 100.00 | 33.54 | 0 | 0 | 0 | 252.9 | 317.5 | 99.74 | 318.4 | 100.00 |
| t11 | delay_100ms | v4 | 3 | 253.4 | 319.4 | 339.6 | 100.00 | 100.00 | 100.00 | 33.57 | 0 | 0 | 0 | 253.2 | 324.3 | 100.00 | 318.8 | 100.00 |
| t11 | delay_100ms | v5 | 1 | 206.6 | 254.8 | 274.9 | 99.97 | 99.97 | 100.00 | 33.57 | 0 | 0 | 0 | 208.0 | 256.9 | 99.74 | 254.7 | 100.00 |
| t11 | delay_100ms | v5 | 2 | 202.9 | 248.4 | 266.9 | 100.00 | 100.00 | 100.00 | 33.51 | 0 | 0 | 0 | 204.1 | 248.3 | 100.00 | 248.4 | 100.00 |
| t11 | delay_100ms | v5 | 3 | 203.7 | 248.8 | 267.8 | 100.00 | 100.00 | 100.00 | 33.50 | 0 | 0 | 0 | 203.7 | 251.2 | 100.00 | 248.6 | 100.00 |
| t15 | delay_loss | v4 | 1 | 301.5 | 532.6 | 726.0 | 93.48 | 93.43 | 100.00 | 33.36 | 0 | 0 | 0 | 297.9 | 558.3 | 92.50 | 529.9 | 93.59 |
| t15 | delay_loss | v4 | 2 | 296.1 | 513.1 | 694.5 | 94.45 | 94.45 | 100.00 | 33.35 | 0 | 0 | 0 | 296.5 | 501.4 | 94.88 | 513.1 | 94.40 |
| t15 | delay_loss | v4 | 3 | 303.9 | 712.2 | 1052.1 | 89.87 | 89.87 | 100.00 | 33.35 | 0 | 0 | 0 | 309.0 | 756.7 | 88.03 | 705.8 | 90.08 |
| t15 | delay_loss | v5 | 1 | 253.0 | 708.7 | 892.0 | 87.75 | 87.74 | 100.00 | 33.36 | 0 | 0 | 0 | 260.3 | 741.7 | 84.12 | 706.7 | 88.15 |
| t15 | delay_loss | v5 | 2 | 244.4 | 530.3 | 804.2 | 93.24 | 93.24 | 100.00 | 33.36 | 0 | 0 | 0 | 249.4 | 555.8 | 91.59 | 528.1 | 93.42 |
| t15 | delay_loss | v5 | 3 | 259.4 | 686.5 | 995.8 | 89.05 | 89.03 | 100.00 | 33.36 | 0 | 0 | 0 | 263.6 | 727.7 | 87.50 | 678.5 | 89.22 |
| t19 | loss_3pct | v4 | 1 | 34.7 | 207.7 | 5488.2 | 96.01 | 96.61 | 100.00 | 41.81 | 0 | 0 | 0 | 93.8 | 6739.2 | 58.03 | 98.8 | 99.99 |
| t19 | loss_3pct | v4 | 2 | 34.2 | 98.9 | 4892.9 | 96.41 | 97.04 | 100.00 | 40.69 | 0 | 0 | 0 | 83.5 | 6494.0 | 62.42 | 93.2 | 100.00 |
| t19 | loss_3pct | v4 | 3 | 32.7 | 226.3 | 3822.4 | 97.26 | 97.64 | 100.00 | 42.06 | 0 | 0 | 0 | 79.2 | 5834.9 | 69.49 | 98.0 | 100.00 |
| t19 | loss_3pct | v5 | 1 | 3.8 | 440.0 | 6338.0 | 95.00 | 95.74 | 100.00 | 42.14 | 0 | 0 | 0 | 584.0 | 7353.0 | 49.04 | 6.3 | 99.95 |
| t19 | loss_3pct | v5 | 2 | 3.5 | 8.0 | 3334.0 | 97.19 | 97.61 | 100.00 | 41.90 | 0 | 0 | 0 | 4.6 | 5254.4 | 69.05 | 5.9 | 100.00 |
| t19 | loss_3pct | v5 | 3 | 3.2 | 217.1 | 4830.9 | 96.59 | 96.97 | 100.00 | 43.03 | 0 | 0 | 0 | 4.8 | 6593.0 | 62.34 | 5.6 | 99.99 |
| t23 | reorder | v4 | 1 | 43.2 | 45.2 | 5874.5 | 97.04 | 94.37 | 100.00 | 94.34 | 0 | 0 | 0 | 2291.2 | 7841.9 | 35.59 | 44.6 | 100.00 |
| t23 | reorder | v4 | 2 | 43.3 | 45.7 | 5876.0 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2289.0 | 7865.4 | 35.35 | 44.7 | 100.00 |
| t23 | reorder | v4 | 3 | 43.2 | 45.9 | 5880.2 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2293.9 | 7871.9 | 35.35 | 44.6 | 100.00 |
| t23 | reorder | v5 | 1 | 43.4 | 45.3 | 5876.8 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2292.6 | 7859.1 | 35.35 | 44.9 | 100.00 |
| t23 | reorder | v5 | 2 | 43.6 | 45.9 | 5881.3 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2295.1 | 7871.2 | 35.35 | 45.2 | 100.00 |
| t23 | reorder | v5 | 3 | 43.5 | 45.8 | 5878.9 | 97.02 | 94.34 | 100.00 | 94.34 | 0 | 0 | 0 | 2293.9 | 7871.5 | 35.35 | 45.1 | 100.00 |

Median P95 vs no-impairment baseline (v4): bandwidth_2mbit 16×, delay_100ms 47×, delay_loss 79×, loss_3pct 31×, reorder 7×

Median P95 vs no-impairment baseline (v5): bandwidth_2mbit 7×, delay_100ms 45×, delay_loss 124×, loss_3pct 39×, reorder 8×

## T4 Reconnect (100 clients, 60 s, 20% drop @15 s for 5 s)

| Test | Network | Version | Run | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err | Recovery P50 ms | Recovery P95 ms | Recovered items |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t4 | None | v4 | 1 | 2.9 | 4.7 | 5.4 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 2.1 | 2.3 | 140 |
| t4 | None | v4 | 2 | 3.0 | 4.8 | 5.4 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 1.9 | 2.1 | 140 |
| t4 | None | v4 | 3 | 3.0 | 4.8 | 5.4 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 1.9 | 2.0 | 140 |
| t4 | None | v5 | 1 | 3.1 | 5.2 | 6.3 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 1.6 | 1.8 | 140 |
| t4 | None | v5 | 2 | 3.0 | 4.8 | 5.4 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 1.9 | 2.0 | 140 |
| t4 | None | v5 | 3 | 3.1 | 5.1 | 6.2 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 2.4 | 2.5 | 140 |
| t8 | bandwidth_2mbit | v4 | 1 | 38.7 | 106.2 | 114.7 | 100.00 | 98.42 | 100.00 | 41.53 | 0 | 0 | 0 | 1.6 | 12.3 | 120 |
| t8 | bandwidth_2mbit | v4 | 2 | 38.2 | 105.8 | 114.0 | 100.00 | 98.42 | 100.00 | 41.54 | 0 | 0 | 0 | 4.2 | 14.5 | 120 |
| t8 | bandwidth_2mbit | v4 | 3 | 38.2 | 106.0 | 114.7 | 100.00 | 98.42 | 100.00 | 41.55 | 0 | 0 | 0 | 8.8 | 26.8 | 120 |
| t8 | bandwidth_2mbit | v5 | 1 | 13.8 | 37.9 | 52.4 | 100.00 | 98.42 | 100.00 | 41.43 | 0 | 0 | 0 | 5.1 | 19.7 | 120 |
| t8 | bandwidth_2mbit | v5 | 2 | 14.0 | 38.2 | 52.7 | 100.00 | 98.42 | 100.00 | 41.43 | 0 | 0 | 0 | 7.9 | 19.6 | 120 |
| t8 | bandwidth_2mbit | v5 | 3 | 14.2 | 38.4 | 52.5 | 100.00 | 98.42 | 100.00 | 41.42 | 0 | 0 | 0 | 10.8 | 23.9 | 120 |
| t12 | delay_100ms | v4 | 1 | 251.5 | 319.3 | 342.6 | 100.00 | 98.16 | 100.00 | 32.90 | 0 | 0 | 0 | 202.0 | 252.1 | 140 |
| t12 | delay_100ms | v4 | 2 | 250.1 | 316.3 | 341.3 | 100.00 | 98.16 | 100.00 | 32.96 | 0 | 0 | 0 | 199.8 | 249.5 | 140 |
| t12 | delay_100ms | v4 | 3 | 247.8 | 315.8 | 341.1 | 100.00 | 98.16 | 100.00 | 32.90 | 0 | 0 | 0 | 204.5 | 236.0 | 140 |
| t12 | delay_100ms | v5 | 1 | 201.9 | 249.2 | 267.7 | 100.00 | 98.16 | 100.00 | 32.95 | 0 | 0 | 0 | 197.6 | 230.7 | 140 |
| t12 | delay_100ms | v5 | 2 | 204.1 | 250.4 | 268.4 | 100.00 | 98.16 | 100.00 | 32.90 | 0 | 0 | 0 | 210.7 | 239.7 | 140 |
| t12 | delay_100ms | v5 | 3 | 202.6 | 248.9 | 267.7 | 100.00 | 98.16 | 100.00 | 32.90 | 0 | 0 | 0 | 209.1 | 263.4 | 140 |
| t16 | delay_loss | v4 | 1 | 301.3 | 628.9 | 840.2 | 90.11 | 88.30 | 100.00 | 32.68 | 0 | 0 | 0 | 245.9 | 362.9 | 163 |
| t16 | delay_loss | v4 | 2 | 308.6 | 929.2 | 1206.4 | 82.36 | 80.20 | 99.34 | 32.46 | 0 | 0 | 0 | 263.5 | 338.9 | 156 |
| t16 | delay_loss | v4 | 3 | 302.2 | 815.4 | 1085.1 | 83.08 | 81.04 | 100.00 | 32.56 | 0 | 0 | 0 | 251.3 | 291.0 | 187 |
| t16 | delay_loss | v5 | 1 | 251.1 | 624.6 | 748.0 | 91.35 | 89.45 | 100.00 | 32.62 | 0 | 0 | 0 | 235.2 | 906.5 | 173 |
| t16 | delay_loss | v5 | 2 | 260.5 | 718.5 | 1035.6 | 89.08 | 86.93 | 100.00 | 32.54 | 0 | 0 | 0 | 258.6 | 583.5 | 189 |
| t16 | delay_loss | v5 | 3 | 252.2 | 759.0 | 1419.6 | 87.66 | 85.89 | 100.00 | 32.66 | 0 | 0 | 0 | 240.0 | 373.0 | 163 |
| t20 | loss_3pct | v4 | 1 | 24.4 | 97.0 | 257.0 | 99.98 | 98.38 | 100.00 | 42.48 | 0 | 0 | 0 | 0.5 | 0.8 | 127 |
| t20 | loss_3pct | v4 | 2 | 24.0 | 96.4 | 267.6 | 100.00 | 98.39 | 100.00 | 43.02 | 0 | 0 | 0 | 0.3 | 0.6 | 126 |
| t20 | loss_3pct | v4 | 3 | 28.1 | 95.2 | 211.3 | 99.98 | 98.37 | 100.00 | 41.64 | 0 | 0 | 0 | 0.5 | 203.7 | 130 |
| t20 | loss_3pct | v5 | 1 | 3.0 | 5.4 | 228.2 | 99.99 | 98.58 | 100.00 | 42.26 | 0 | 0 | 0 | 1.6 | 1.7 | 124 |
| t20 | loss_3pct | v5 | 2 | 2.8 | 13.7 | 213.6 | 99.98 | 98.55 | 100.00 | 42.95 | 0 | 0 | 0 | 1.4 | 1.6 | 126 |
| t20 | loss_3pct | v5 | 3 | 2.9 | 5.3 | 207.7 | 99.99 | 98.64 | 100.00 | 42.46 | 0 | 0 | 0 | 2.0 | 12.3 | 122 |
| t24 | reorder | v4 | 1 | 43.0 | 44.6 | 45.2 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.4 | 40.5 | 120 |
| t24 | reorder | v4 | 2 | 42.9 | 44.6 | 45.2 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.2 | 40.6 | 120 |
| t24 | reorder | v4 | 3 | 42.9 | 44.5 | 45.0 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.3 | 40.7 | 120 |
| t24 | reorder | v5 | 1 | 43.3 | 45.1 | 45.5 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.4 | 40.9 | 120 |
| t24 | reorder | v5 | 2 | 43.3 | 45.1 | 45.7 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.3 | 40.9 | 120 |
| t24 | reorder | v5 | 3 | 43.0 | 44.9 | 45.7 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.3 | 40.7 | 120 |

Median P95 vs no-impairment baseline (v4): bandwidth_2mbit 22×, delay_100ms 66×, delay_loss 169×, loss_3pct 20×, reorder 9×

Median P95 vs no-impairment baseline (v5): bandwidth_2mbit 7×, delay_100ms 49×, delay_loss 140×, loss_3pct 1×, reorder 9×

