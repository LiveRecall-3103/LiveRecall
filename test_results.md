# LiveRecall Public Test Results

All 24 tests were run 3 times each (`run_demo.py --runs 3`, server restarted per run). Every value below is the **median of the 3 runs**, taken per metric. Raw per-run summaries are in `tN_run0X.json` / `.csv`.

## Test matrix

Each network profile runs the same four public scenarios (T1–T4) via `run_public_tests.sh`:

| Network profile | `tc` setting on `lo` | T1 Basic | T2 Scale | T3 Slow | T4 Reconnect |
|---|---|---|---|---|---|
| None (baseline) | – | t1 | t2 | t3 | t4 |
| delay_loss | netem delay 120ms ±30ms, loss 3% | t5 | t6 | t7 | t8 |
| bandwidth_2mbit | tbf rate 2mbit, burst 32kbit, latency 400ms | t9 | t10 | t11 | t12 |
| delay_100ms | netem delay 100ms ±20ms | t13 | t14 | t15 | t16 |
| loss_3pct | netem loss 3% | t17 | t18 | t19 | t20 |
| reorder | netem delay 20ms, reorder 20% 50% | t21 | t22 | t23 | t24 |

## Key findings

- **Correctness held under every profile.** Final completeness is 100% in all 24 tests, with 0 duplicates, 0 stale finals and 0 connection errors.
- **delay_loss is by far the worst profile.** P95 caption age rises to ~1 s (150–435× baseline). Fresh-final ratio drops to ~18–31% and normal update coverage to ~10–25%, so most intermediate revisions are superseded before they arrive. Reconnect recovery goes from ~2 ms to ~21 s (P50) / ~37 s (P95).
- **Fixed delay shifts latency but doesn't hurt freshness.** delay_100ms adds ~215 ms to P50 and reorder (20 ms) adds ~40 ms. That is roughly twice the netem value, because a caption crosses `lo` twice (source → server → client). Fresh ratios stay at baseline levels in both.
- **Loss alone mostly hits the tail.** loss_3pct leaves P50/P95 near baseline, but P99 jumps from ~3–7 ms to ~200 ms in T1/T2 (TCP retransmission timeout) and update coverage drops ~3–4 points.
- **Bandwidth matters only at scale.** At 20 clients 2 mbit is close to baseline (P95 3.9 ms). At 100 clients P95 rises to ~42 ms. Freshness and coverage stay unchanged.
- **Slow readers stay isolated (T3).** Under every profile except delay_loss, normal-client freshness stays at ~100% and normal P95 tracks the profile's baseline latency, while slow clients sit at ~4–8 s age. Under delay_loss, normal fresh % falls to 46%. The ~90.7% fresh-final and ~91.5% coverage in T3 come from the slow clients and are the same across profiles.
- **Reconnect (T4)** recovery time follows the link latency (≈2 ms baseline, 40 ms reorder, 50 ms 2 mbit, 190 ms delay_100ms) except for delay_loss, where it degrades badly.

## T1 Basic (20 clients, 20 s)

| Test | Network | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 | None | 1.5 | 2.3 | 3.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t5 | delay_loss | 402.5 | 984.5 | 1182.0 | 66.46 | 25.91 | 100.00 | 24.62 | 0 | 0 | 0 |
| t9 | bandwidth_2mbit | 1.4 | 3.9 | 6.2 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t13 | delay_100ms | 217.5 | 277.9 | 309.3 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t17 | loss_3pct | 1.5 | 2.4 | 203.2 | 100.00 | 100.00 | 100.00 | 96.89 | 0 | 0 | 0 |
| t21 | reorder | 41.5 | 42.6 | 43.0 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |

P95 vs no-impairment baseline: delay_loss 435×, bandwidth_2mbit 2×, delay_100ms 123×, loss_3pct 1×, reorder 19×

## T2 Scale (100 clients, 40 s)

| Test | Network | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t2 | None | 3.6 | 5.6 | 6.5 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t6 | delay_loss | 433.2 | 1000.2 | 1243.4 | 55.28 | 20.61 | 100.00 | 12.78 | 0 | 0 | 0 |
| t10 | bandwidth_2mbit | 22.3 | 42.7 | 46.7 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t14 | delay_100ms | 218.1 | 284.3 | 317.6 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |
| t18 | loss_3pct | 4.1 | 7.9 | 209.3 | 100.00 | 99.65 | 100.00 | 96.50 | 0 | 0 | 0 |
| t22 | reorder | 44.0 | 46.2 | 48.4 | 100.00 | 100.00 | 100.00 | 100.00 | 0 | 0 | 0 |

P95 vs no-impairment baseline: delay_loss 178×, bandwidth_2mbit 8×, delay_100ms 51×, loss_3pct 1×, reorder 8×

## T3 Slow readers (100 clients, 60 s, 10% slow @500 ms)

| Test | Network | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err | Slow P50 ms | Slow P95 ms | Slow fresh % | Normal P95 ms | Normal fresh % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t3 | None | 4.3 | 8.8 | 3301.9 | 98.47 | 90.79 | 100.00 | 91.49 | 0 | 0 | 0 | 4204.3 | 8103.5 | 5.88 | 8.5 | 100.00 |
| t7 | delay_loss | 727.5 | 1320.9 | 4369.7 | 41.28 | 18.12 | 100.00 | 9.69 | 0 | 0 | 0 | 994.1 | 5634.1 | 3.73 | 1066.7 | 46.10 |
| t11 | bandwidth_2mbit | 20.4 | 40.1 | 3324.7 | 98.47 | 90.67 | 100.00 | 91.49 | 0 | 0 | 0 | 4242.4 | 7889.6 | 5.88 | 39.0 | 100.00 |
| t15 | delay_100ms | 220.6 | 292.8 | 3494.1 | 98.43 | 90.45 | 100.00 | 91.50 | 0 | 0 | 0 | 4518.7 | 8085.0 | 3.81 | 284.7 | 100.00 |
| t19 | loss_3pct | 4.4 | 9.5 | 3754.6 | 98.24 | 90.55 | 100.00 | 88.63 | 0 | 0 | 0 | 4299.8 | 8115.1 | 5.88 | 9.0 | 99.97 |
| t23 | reorder | 43.6 | 45.6 | 3341.4 | 98.47 | 90.66 | 100.00 | 91.49 | 0 | 0 | 0 | 4244.0 | 8146.5 | 5.88 | 45.4 | 100.00 |

P95 vs no-impairment baseline: delay_loss 151×, bandwidth_2mbit 5×, delay_100ms 33×, loss_3pct 1×, reorder 5×

## T4 Reconnect (100 clients, 60 s, 20% drop @15 s for 5 s)

| Test | Network | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final complete % | Update coverage % | Dup | Stale | Conn err | Recovery P50 ms | Recovery P95 ms | Recovered items |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t4 | None | 3.6 | 6.7 | 8.5 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 2.1 | 2.3 | 140 |
| t8 | delay_loss | 490.5 | 1034.9 | 1316.2 | 50.44 | 19.50 | 100.00 | 11.06 | 0 | 0 | 0 | 20764.3 | 36830.7 | 6073 |
| t12 | bandwidth_2mbit | 21.8 | 42.5 | 47.4 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 49.4 | 52.7 | 131 |
| t16 | delay_100ms | 219.6 | 283.8 | 317.9 | 100.00 | 98.16 | 100.00 | 97.98 | 0 | 0 | 0 | 191.7 | 234.6 | 160 |
| t20 | loss_3pct | 3.9 | 8.3 | 60.1 | 99.98 | 97.84 | 100.00 | 95.70 | 0 | 0 | 0 | 1.5 | 12.0 | 197 |
| t24 | reorder | 43.1 | 45.0 | 45.9 | 100.00 | 98.42 | 100.00 | 98.25 | 0 | 0 | 0 | 40.4 | 40.8 | 120 |

P95 vs no-impairment baseline: delay_loss 155×, bandwidth_2mbit 6×, delay_100ms 42×, loss_3pct 1×, reorder 7×

## Appendix: per-run values (P95 ms / Fresh final % / Final complete %)

| Test | Network | Scenario | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|---|
| t1 | None | T1 | 3.3 / 100.00 / 100.00 | 2.3 / 100.00 / 100.00 | 2.0 / 100.00 / 100.00 |
| t2 | None | T2 | 5.6 / 100.00 / 100.00 | 5.5 / 100.00 / 100.00 | 5.8 / 100.00 / 100.00 |
| t3 | None | T3 | 8.8 / 90.79 / 100.00 | 6.2 / 90.79 / 100.00 | 9.1 / 90.79 / 100.00 |
| t4 | None | T4 | 5.8 / 98.42 / 100.00 | 6.7 / 98.42 / 100.00 | 7.4 / 98.42 / 100.00 |
| t5 | delay_loss | T1 | 943.1 / 31.36 / 100.00 | 984.5 / 25.00 / 100.00 | 996.9 / 25.91 / 100.00 |
| t6 | delay_loss | T2 | 1083.3 / 19.78 / 100.00 | 991.6 / 22.49 / 100.00 | 1000.2 / 20.61 / 100.00 |
| t7 | delay_loss | T3 | 1851.4 / 18.12 / 100.00 | 1320.9 / 17.18 / 100.00 | 1255.1 / 18.36 / 100.00 |
| t8 | delay_loss | T4 | 1038.3 / 19.53 / 100.00 | 1034.9 / 18.92 / 100.00 | 1013.4 / 19.50 / 100.00 |
| t9 | bandwidth_2mbit | T1 | 3.5 / 100.00 / 100.00 | 3.9 / 100.00 / 100.00 | 4.1 / 100.00 / 100.00 |
| t10 | bandwidth_2mbit | T2 | 42.6 / 100.00 / 100.00 | 42.7 / 100.00 / 100.00 | 42.8 / 100.00 / 100.00 |
| t11 | bandwidth_2mbit | T3 | 39.5 / 90.66 / 100.00 | 40.1 / 90.78 / 100.00 | 40.2 / 90.67 / 100.00 |
| t12 | bandwidth_2mbit | T4 | 42.5 / 98.42 / 100.00 | 42.5 / 98.42 / 100.00 | 42.5 / 98.42 / 100.00 |
| t13 | delay_100ms | T1 | 276.3 / 100.00 / 100.00 | 277.9 / 100.00 / 100.00 | 286.9 / 100.00 / 100.00 |
| t14 | delay_100ms | T2 | 283.4 / 99.43 / 100.00 | 284.3 / 100.00 / 100.00 | 284.8 / 100.00 / 100.00 |
| t15 | delay_100ms | T3 | 292.8 / 90.38 / 100.00 | 294.0 / 90.45 / 100.00 | 291.0 / 90.46 / 100.00 |
| t16 | delay_100ms | T4 | 282.9 / 98.14 / 100.00 | 283.8 / 98.16 / 100.00 | 287.3 / 98.16 / 100.00 |
| t17 | loss_3pct | T1 | 2.4 / 100.00 / 100.00 | 2.3 / 100.00 / 100.00 | 2.9 / 100.00 / 100.00 |
| t18 | loss_3pct | T2 | 7.9 / 100.00 / 100.00 | 6.0 / 99.65 / 100.00 | 10.5 / 99.20 / 100.00 |
| t19 | loss_3pct | T3 | 9.9 / 90.79 / 100.00 | 9.5 / 90.18 / 100.00 | 9.4 / 90.55 / 100.00 |
| t20 | loss_3pct | T4 | 8.3 / 98.21 / 100.00 | 9.0 / 97.84 / 100.00 | 6.0 / 97.47 / 100.00 |
| t21 | reorder | T1 | 42.0 / 100.00 / 100.00 | 42.6 / 100.00 / 100.00 | 42.6 / 100.00 / 100.00 |
| t22 | reorder | T2 | 46.4 / 100.00 / 100.00 | 46.2 / 100.00 / 100.00 | 45.8 / 100.00 / 100.00 |
| t23 | reorder | T3 | 45.8 / 90.66 / 100.00 | 45.2 / 90.66 / 100.00 | 45.6 / 90.66 / 100.00 |
| t24 | reorder | T4 | 44.8 / 98.42 / 100.00 | 45.0 / 98.42 / 100.00 | 45.0 / 98.42 / 100.00 |
