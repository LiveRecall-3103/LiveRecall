# Team Contributions

| Member | Main responsibilities | Components / experiments / report sections | Agreed contribution % |
|---|---|---|---:|
| Aw Ming Xuan (`@icyyolo`, A0308470H) | Browser client and lag-control tuning; bonus ASR caption source | **Components:** `client/` (recall filters 15/30/60 s, revision replacement, 90 s pruning, auto-reconnect with resume state, HISTORY merge); lag detection/exit in `solution_server.py` (idle-RTT baseline, two-soft-pong entry, shared-bottleneck exit, slow-reader pinning, finals sent without waiting for pong); `bonus_asr/`. **Experiments:** public test runs, ASR demo. **Report:** Client (`app.js`), ASR Bonus appendix (Integration, Pipeline, How to run it, Limitations) | 25% |
| Kosolpattanadurong Thitiwat (`@CATISNOTSODIUM`, A0305613N) |Client browser (frontend)  Reports: architecture and Protocol, Recovery semantics, Results/Discussion write-up and figures, overall editing and PDF generation | 25% |
| Lee Zhao Rui (`@oilyfishball`, A0308380H) | Starter-kit setup; server send path and flow control | **Components:** per-connection send queues, unicast error handling, overflow drop, stale-packet removal, ping-based flow control, version control, smart pacing/pipelining in `solution_server.py`; repo/docs organisation. **Experiments:** T1–T3 runs (`t1_*`, `t2_*`, `t3_*`, `t3_opt_*`), `test_results.md`. **Report:** Server: Sending to clients, Receive buffer estimation, Results | 25% |
| Wong Ji Kean (`@ji-just-ji`, A0252449Y) | Caption store and Source→Server parsing; batching and data-structure optimisation | **Components:** `server/store.py` and update parsing with tests (`tests/`), batch-sending optimisation, moving heavy work into the store, send-timing/lag constant tuning, `run_stress.py`. **Experiments:** stress tests and demo runs (`demo_results_run0*`). **Report:** Server: storing captions, Addressing the two advanced challenges | 25% |

**Total: 100%**

## Shared / integration work

- Merging feature branches (`feat/server-client-comms`, `feat/version-control`, `opt/disconnect-window`, `opt/Client-DS`, `bonus/ASR-Source`) into `main` and resolving conflicts was done jointly via pull requests.
- Lag-exit constant tuning was a joint effort between Aw Ming Xuan and Wong Ji Kean.
- All members reviewed the final report and results.

Git history is supporting evidence, not a substitute for this statement.
