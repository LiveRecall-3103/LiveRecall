from LiveRecall.server.store import CaptionStore, Entry, ACCEPTED, STALE, DUP_FINAL

def E(seg, rev, final, ts): return Entry(seg, rev, final, ts, f"s{seg}r{rev}", "{}")

s = CaptionStore(keep_seconds=90)
assert s.apply(E(1, 1, False, 100.0)) == ACCEPTED
assert s.apply(E(1, 2, False, 100.2)) == ACCEPTED
assert s.apply(E(1, 1, False, 100.3)) == STALE          # older revision
assert s.apply(E(1, 3, True,  100.4)) == ACCEPTED
assert s.apply(E(1, 4, False, 100.5)) == DUP_FINAL      # final never replaced
assert s.contig_final == 1

s.apply(E(3, 1, True, 101.0))                           # segment 2 missing
assert s.contig_final == 1                              # gap: counter waits
s.apply(E(2, 1, True, 100.9))
assert s.contig_final == 3                              # gap filled, counter jumps

s.apply(E(4, 1, True, 300.0))                           # >90 s later
assert s.earliest == 4 and len(s.entries) == 1          # old segments pruned
print("ok")

s = CaptionStore(keep_seconds=90)
for i in range(1, 101):                      # 100 finals, one per second, ts 1000..1099
    s.apply(E(i, 1, True, 1000.0 + i - 1))
s.apply(E(101, 1, False, 1100.0))            # an active draft

h = s.get_history(0, 0, 30)
assert [e.segment for e in h] == list(range(71, 101))     # 30 finals; seg 70 (ts 1069) is just outside the window

h = s.get_history(0, 0, 9999)                              # clamped to 60 s
assert h[0].segment >= 40 and h[-1].segment == 100

h = s.get_history(95, 1, 60)                               # reconnect: client holds up to 95
assert [e.segment for e in h] == [96, 97, 98, 99, 100]

assert s.get_history(100, 1, 60) == []                     # nothing missed
assert s.get_history(0, 0, 0) == []
assert len(s.get_history("x", None, "y")) > 0              # type: ignore # garbage input doesn't crash
assert [e.segment for e in s.get_history(0, 0, 60)] == sorted(e.segment for e in s.get_history(0, 0, 60))