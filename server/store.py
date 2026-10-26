from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import math


@dataclass
class Entry:
    segment: int
    revision: int
    final: bool
    source_ts: float
    text: str
    raw: str            # original JSON string, so we can forward it without re-encoding

ACCEPTED, STALE, DUP_FINAL, TOO_OLD = "ACCEPTED", "STALE", "DUP_FINAL", "TOO_OLD"
HISTORY_CAP_SECONDS = 60.0   # spec: recovery is "up to 60 seconds"


class CaptionStore:
    def __init__(self, keep_seconds: float = 90.0, max_items: int = 500):
        self.keep_seconds = keep_seconds
        self.max_items = max_items            # hard cap, in case timestamps misbehave
        self.entries: dict[int, Entry] = {}   # segment -> newest Entry
        self.order: deque[int] = deque()      # segment numbers, ascending
        self.latest_ts = 0.0                  # newest source_ts seen
        self.contig_final = 0                 # highest N where segments 1..N are all final

    # ---- main entry point -------------------------------------------------
    def apply(self, new: Entry) -> str:
        cur = self.entries.get(new.segment)

        if cur is None:
            # not in memory: was it finished and pruned, or pruned while unfinished?
            if new.segment <= self.contig_final:              # already finalized
                return DUP_FINAL
            if self.order and new.segment < self.order[0]:    # pruned
                return TOO_OLD
            self.entries[new.segment] = new                   # add to memory
            self.order.append(new.segment)                    # append to order
            
            # handle out-of-order arrival (rare): if the new segment is less than the previous one, sort the order
            # TODO Look into optimizing this, as sorting the entire order every time a new entry is added could be inefficient for large datasets. 
            # Consider using a more efficient data structure or algorithm to maintain order without needing to sort the entire list each time.
            # Heap?
            if len(self.order) > 1 and self.order[-1] < self.order[-2]:
                self.order = deque(sorted(self.entries))      # out-of-order arrival (rare)
        else:
            if cur.final:
                return DUP_FINAL              # a final is never replaced
            if new.revision <= cur.revision:
                return STALE                  # older or repeated revision
            self.entries[new.segment] = new   # replace, don't mutate

        self.latest_ts = max(self.latest_ts, new.source_ts)
        if new.final:
            self._advance_contig()
        self._prune()
        return ACCEPTED

    # ---- helpers ----------------------------------------------------------
    def _advance_contig(self) -> None:
        while True:
            e = self.entries.get(self.contig_final + 1)
            if e is None or not e.final:
                break
            self.contig_final += 1

    def _prune(self) -> None:
        cutoff = self.latest_ts - self.keep_seconds
        while self.order and (
            self.entries[self.order[0]].source_ts < cutoff
            or len(self.order) > self.max_items
        ):
            del self.entries[self.order.popleft()]

    # ---- reads (used later for HISTORY) ------------------------------------
    @property
    def earliest(self) -> int | None:
        return self.order[0] if self.order else None

    @property
    def latest(self) -> int | None:
        return self.order[-1] if self.order else None

    def active(self) -> list[Entry]:
        return [self.entries[s] for s in self.order if not self.entries[s].final]

    def finals_after(self, last_segment: int, seconds: float) -> list[Entry]:
        cutoff = self.latest_ts - min(seconds, 60)
        return [e for s in self.order
                if s > last_segment
                and (e := self.entries[s]).final
                and e.source_ts >= cutoff]
        
        
    # ---- HISTORY support ----------------------------------------------------
    @staticmethod
    def _clean_seconds(value) -> float:
        # client input is untrusted: missing/garbage -> the full 60 s (safest for completeness)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return HISTORY_CAP_SECONDS
        return max(0.0, min(float(value), HISTORY_CAP_SECONDS))

    @staticmethod
    def _clean_int(value) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    def get_history(self, last_segment=0, last_revision=0, history_seconds=30) -> list[Entry]:
        """Finalized entries the client lacks, oldest -> newest, at most 60 s back.

        Synchronous, no await. Returns a new list, so later store changes can't
        alter it. The caller turns it into a HISTORY message and sends it.
        """
        seconds = self._clean_seconds(history_seconds)
        last_seg = self._clean_int(last_segment)
        last_rev = self._clean_int(last_revision)
        if seconds == 0 or not self.order:
            return []

        cutoff = self.latest_ts - seconds
        out: list[Entry] = []
        for seg in reversed(self.order):          # newest first
            if seg < last_seg:
                break                              # everything older is already held
            e = self.entries[seg]
            if not e.final:
                continue                           # HISTORY carries finals only
            if seg == last_seg and e.revision <= last_rev:
                continue                           # client already has this exact final
            if e.source_ts < cutoff:
                continue                           # outside the requested window
            out.append(e)
        out.reverse()                              # oldest -> newest, as the spec requires
        return out