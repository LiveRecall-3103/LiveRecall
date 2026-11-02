#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall server.

Versions (config.VERSION):
  0  naive broadcast
  2  per-client queue + ping flow control
  3  + lag-window disconnect
  4  + opt 2: a lagging client with 2+ queued finals gets them as ONE HISTORY
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter, deque
from typing import Any

import websockets

from config import VERSION
from server.store import CaptionStore, Entry, ACCEPTED

NAIVE = VERSION == 0
PING_FLOW_CONTROL = VERSION >= 2
LAG_WINDOW_DROP = VERSION >= 3
BATCH_FINALS = VERSION >= 4              # opt 2

MAX_LAG_WINDOW = 10.0   # s: oldest queued item older than this -> disconnect (V3)
LAG_ENTER = 0.4         # s: oldest queued age or pong RTT above this -> lagging
LAG_EXIT_RTT = 0.15     # s: when nothing is left to send and RTT is below this -> normal

# Counters for the report
LAG_DROPS = 0           # clients disconnected by the lag-window check (V3)
LAG_ENTRIES = 0         # times a client entered lag mode (V4)
BATCHES = 0             # mass sends (V4)
BATCHED_FINALS = 0      # finals delivered inside mass sends (V4)
LOG_ID = None   # set to a client id taken from a [LAG-ENTER] line

LAG_AGE_ENTER = 0.5     # s: producer-side safety net (sender stuck, dirty is ageing)
STALL_RTT = 0.15        # s: a pong slower than this means the client's reader is paused
CAL_STALLS = 3          # consecutive stalled pongs needed to confirm lag and measure iv
SAFETY_MSGS = 2.0       # extra messages assumed in the client's queue
DEPTH_FINAL = 1.0       # send finals when estimated unread messages <= this
DEPTH_PROV = 0.2        # send provisionals only when the client is ~idle
LAG_FAST_IV = 0.15      # s: lag mode may only end if the client is proven fast
LAG_EXIT_RTT = 0.15     # s

# ---------------------------------------------------------------------------
# Per-client state
# ---------------------------------------------------------------------------
class Client:
    def __init__(self, ws, client_id, maxsize: int = 100):
        self.ws = ws
        self.client_id = client_id
        self.ready = asyncio.Event()
        self.maxsize = maxsize

        self.initial: str | None = None       # late-join / resume HISTORY
        self.dirty: dict[int, float] = {}     # normal mode only: segment -> first_dirty_ts
        self.last_final_sent = 0              # cursor: highest final segment sent
        self.sent_rev: dict[int, int] = {}    # provisional segment -> highest revision sent

        # pong measurement
        self.rtt = 0.0
        self.stalls: list[float] = []         # completion times of consecutive stalled pongs
        self.slept = False                    # a deliberate wait preceded the current send

        # model of the client's hidden receive queue
        self.iv: float | None = None          # client read interval (s), measured
        self.cap_est: float | None = None     # client queue size, measured
        self.depth = 0.0                      # estimated unread messages right now
        self.depth_ts = time.monotonic()
        self.sent_total = 0                   # frames sent on this connection
        self.t_first: float | None = None     # when the first frame was sent

        self.lagging = False
        self.lag_since = 0.0

    # ---- queries ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.dirty) + (self.initial is not None)

    def oldest_age(self, now: float | None = None) -> float:
        if not self.dirty:
            return 0.0
        if now is None:
            now = time.monotonic()
        return now - next(iter(self.dirty.values()))

    # ---- producer side --------------------------------------------------------
    def set_initial(self, raw: str, cursor: int) -> None:
        self.initial = raw
        self.last_final_sent = max(self.last_final_sent, cursor)
        self.ready.set()

    def enqueue(self, segment: int) -> bool:
        """Normal mode: mark the segment dirty. Lag mode: just wake the sender,
        which reads everything it needs from the store. False = cut the client off."""
        global LAG_DROPS
        if BATCH_FINALS:
            self._maybe_enter_lag()
        if self.lagging:
            self.ready.set()
            return True
        if segment not in self.dirty:             # already dirty = coalesced, keep age
            if len(self.dirty) >= self.maxsize:
                return False
            now = time.monotonic()
            if LAG_WINDOW_DROP and self.oldest_age(now) > MAX_LAG_WINDOW:
                LAG_DROPS += 1
                return False
            self.dirty[segment] = now
        self.ready.set()
        return True

    # ---- lag detection -----------------------------------------------------------
    def _enter_lag(self, now: float) -> None:
        global LAG_ENTRIES
        self.lagging = True
        LAG_ENTRIES += 1
        self.lag_since = now
        self.dirty.clear()                 # the store plus the cursor supply everything

    def _maybe_enter_lag(self) -> None:
        """Safety net: the sender is stuck so long that dirty is ageing."""
        if not self.lagging and self.oldest_age() > LAG_AGE_ENTER:
            self._enter_lag(time.monotonic())

    # ---- queue model ---------------------------------------------------------------
    def _decay(self, now: float) -> None:
        if self.iv:
            self.depth = max(0.0, self.depth - (now - self.depth_ts) / self.iv)
        self.depth_ts = now

    def _set_full(self, now: float) -> None:
        """The client's queue is known to be full right now."""
        self.depth = (self.cap_est or 0.0) + SAFETY_MSGS
        self.depth_ts = now

    def wait_time(self, now: float, target: float) -> float:
        """Seconds until the estimated backlog falls to `target` messages."""
        if not self.iv:
            return 0.0                     # not calibrated yet: pace by the pong clock
        self._decay(now)
        return max(0.0, (self.depth - target) * self.iv)

    def send_target(self, store: CaptionStore) -> float:
        return DEPTH_FINAL if store.newest_final_seg() > self.last_final_sent else DEPTH_PROV

    def on_sent(self, now: float) -> None:
        if self.t_first is None:
            self.t_first = now
        self.sent_total += 1
        if self.iv:
            self._decay(now)
            self.depth += 1.0

    def on_pong(self, now: float, rtt: float) -> None:
        stalled = rtt > STALL_RTT
        if self.slept:                     # we waited first; completions are not back-to-back
            self.slept = False
            self.stalls.clear()
            if stalled and self.lagging and self.cap_est:
                # the model said "drained" but the queue was still full: it was too small
                self.cap_est = max(self.cap_est * 1.25, self.cap_est + 2.0)
                self._set_full(now)
                print(f"[LAG-UNDERSHOT] id={self.client_id} rtt={rtt:.2f} "
                      f"cap_est->{self.cap_est:.1f}", flush=True)
            return
        if not stalled:
            self.stalls.clear()
            return
        self.stalls.append(now)
        if len(self.stalls) > CAL_STALLS:
            self.stalls.pop(0)
        if len(self.stalls) >= CAL_STALLS:
            self._calibrate(now)

    def _calibrate(self, now: float) -> None:
        s = self.stalls
        iv = max(0.05, (s[-1] - s[0]) / (len(s) - 1))   # exactly one read per completion
        self.iv = iv if self.iv is None else 0.5 * self.iv + 0.5 * iv
        if self.cap_est is None:
            reads = 1.0 + (now - (self.t_first or now)) / self.iv
            self.cap_est = max(2.0, self.sent_total - reads)
        if not self.lagging:
            self._enter_lag(now)
        self._set_full(now)
        self.stalls.clear()
        print(f"[LAG-CAL] id={self.client_id} t={now - (self.t_first or now):.1f} "
              f"iv={self.iv:.2f} sent={self.sent_total} cap_est={self.cap_est:.1f}", flush=True)

    # ---- consumer side: the sending decision --------------------------------------
    def next_message(self, store: CaptionStore) -> str | None:
        global BATCHES, BATCHED_FINALS

        # 1. Late-join / resume HISTORY first.
        if self.initial is not None:
            raw, self.initial = self.initial, None
            return raw

        # 2. Normal mode: every revision, in order.
        if not BATCH_FINALS:
            return self._next_fifo(store)
        self._maybe_enter_lag()
        if not self.lagging:
            return self._next_fifo(store)

        # 3. Lag mode, priority 1: every final the client lacks, in ONE message.
        missing = store.finals_after_segment(self.last_final_sent)
        if missing:
            self.last_final_sent = missing[-1].segment
            self._forget_covered_revs()
            if len(missing) == 1:
                return missing[0].raw
            BATCHES += 1
            BATCHED_FINALS += len(missing)
            return '{"type":"HISTORY","items":[' + ",".join(e.raw for e in missing) + "]}"

        # 4. Lag mode, priority 2: oldest active segment with a revision the client lacks.
        for e in store.active_after(self.last_final_sent):
            if e.revision > self.sent_rev.get(e.segment, 0):
                self.sent_rev[e.segment] = e.revision
                return e.raw

        # 5. Caught up. Leave lag mode only if the client is proven fast.
        if (self.rtt < LAG_EXIT_RTT and (self.iv is None or self.iv < LAG_FAST_IV)
                and time.monotonic() - self.lag_since > 2.0):
            self.lagging = False
            self.stalls.clear()
        return None

    # ---- internals ----------------------------------------------------------------
    def _next_fifo(self, store: CaptionStore) -> str | None:
        while self.dirty:
            seg = next(iter(self.dirty))
            del self.dirty[seg]
            e = store.entries.get(seg)
            if e is None:                         # pruned from the store
                continue
            if seg <= self.last_final_sent:       # client already holds this segment's final
                continue
            if e.final:
                self.last_final_sent = seg
                self.sent_rev.pop(seg, None)
            else:
                self.sent_rev[seg] = e.revision
            return e.raw
        return None

    def _forget_covered_revs(self) -> None:
        for s in [s for s in self.sent_rev if s <= self.last_final_sent]:
            del self.sent_rev[s]

CLIENTS: set[Any] = set()

# Global caption store, shared by all source connections.
store = CaptionStore(keep_seconds=120.0, max_items=500)


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
async def broadcast_naively(raw_message: str) -> None:
    """V0: send directly to every client, waiting for all sends."""
    if not CLIENTS:
        return
    snapshot = list(CLIENTS)
    results = await asyncio.gather(
        *(client.send(raw_message) for client in snapshot),
        return_exceptions=True,
    )
    for client, result in zip(snapshot, results):
        if isinstance(result, Exception):
            CLIENTS.discard(client)


async def broadcast(segment: int) -> None:
    """Mark the segment dirty for every client. Never awaits."""
    if not CLIENTS:
        return
    for client in list(CLIENTS):
        if not client.enqueue(segment):
            CLIENTS.discard(client)
            asyncio.create_task(client.ws.close(code=1013, reason="client too slow"))

async def unicast(client: Client) -> None:
    try:
        while True:
            await client.ready.wait()
            while True:
                # Pace: in lag mode wait until the client's estimated backlog is small.
                # Re-check every 100 ms so a final that arrives mid-wait is not held back.
                while client.lagging and client.iv:
                    w = client.wait_time(time.monotonic(), client.send_target(store))
                    if w <= 0:
                        break
                    client.slept = True
                    await asyncio.sleep(min(w, 0.1))
                msg = client.next_message(store)     # chosen AFTER the wait
                if msg is None:
                    break
                t0 = time.monotonic()
                await client.ws.send(msg)
                client.on_sent(t0)
                if PING_FLOW_CONTROL:
                    await (await client.ws.ping())
                now = time.monotonic()
                client.rtt = now - t0
                client.on_pong(now, client.rtt)
            # No await between the None above and this clear, so no wake-up is lost.
            client.ready.clear()
    except websockets.ConnectionClosed:
        pass
    except Exception as e:                           # never die silently
        print(f"[SENDER-CRASH] id={client.client_id} {type(e).__name__}: {e}", flush=True)
        raise


# ---------------------------------------------------------------------------
# Source side
# ---------------------------------------------------------------------------
def parse_update(msg: dict, raw: str) -> Entry | None:
    try:
        seg, rev = msg["segment"], msg["revision"]
        fin, ts, text = msg["final"], msg["source_ts"], msg["text"]
    except KeyError:
        return None
    if type(seg) is not int or type(rev) is not int or seg < 1 or rev < 1:
        return None
    if type(fin) is not bool or not isinstance(text, str):
        return None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    return Entry(seg, rev, fin, float(ts), text, raw)


async def handle_source(ws, hello: dict[str, Any]) -> None:
    session = hello.get("session")
    print(f"source connected: session={session}", flush=True)
    stats = Counter()
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                stats["bad_json"] += 1
                continue
            if not isinstance(msg, dict):
                stats["not_object"] += 1
                continue

            msg_type = msg.get("type")
            if msg_type == "CAPTION_UPDATE":
                entry = parse_update(msg, raw)
                if entry is None:
                    stats["invalid"] += 1
                    continue
                result = store.apply(entry)
                stats[result] += 1
                if result == ACCEPTED:
                    if NAIVE:
                        await broadcast_naively(raw)
                    else:
                        await broadcast(entry.segment)
            elif msg_type == "SOURCE_DONE":
                print("source finished", flush=True)
                dump_store(stats)
            else:
                continue
    finally:
        print("source disconnected", flush=True)


def dump_store(stats) -> None:
    print("---- store summary ----")
    print("results      :", dict(stats))
    print("entries      :", len(store.entries))
    print("earliest     :", store.earliest, " latest:", store.latest)
    print("contig_final :", store.contig_final)
    print("lag entries  :", LAG_ENTRIES, " lag drops:", LAG_DROPS)
    print("batches      :", BATCHES, " finals in batches:", BATCHED_FINALS)


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------
async def handle_client(ws, hello: dict[str, Any]) -> None:
    """V0 naive path."""
    client_id = hello.get("client_id")
    await ws.send(json.dumps({"type": "HISTORY", "items": []}))
    CLIENTS.add(ws)
    print(f"client connected: id={client_id}; clients={len(CLIENTS)}", flush=True)
    try:
        async for _ in ws:
            pass
    finally:
        CLIENTS.discard(ws)
        print(f"client disconnected: id={client_id}; clients={len(CLIENTS)}", flush=True)

async def handle_client_new(ws, hello: dict[str, Any]) -> None:
    client_id = hello.get("client_id")
    try:
        last_segment = int(hello.get("last_segment", 0))
        last_revision = int(hello.get("last_revision", 0))
        history_seconds = max(min(int(hello.get("history_seconds", 30)), 60), 0)
    except (TypeError, ValueError):
        last_segment, last_revision, history_seconds = 0, 0, 30

    history = store.get_history(last_segment, last_revision, history_seconds)
    raw = json.dumps({"type": "HISTORY", "items": [json.loads(e.raw) for e in history]})

    client = Client(ws=ws, client_id=client_id)
    client.set_initial(raw, max(last_segment, store.newest_final_seg()))
    CLIENTS.add(client)
    sender = asyncio.create_task(unicast(client))

    if last_segment == 0 and last_revision == 0:
        print(f"client connected: id={client_id}; clients={len(CLIENTS)}", flush=True)
    else:
        print(f"client reconnected: id={client_id}; clients={len(CLIENTS)}", flush=True)

    try:
        async for _ in ws:
            pass
    except websockets.ConnectionClosed:
        pass
    finally:
        sender.cancel()
        CLIENTS.discard(client)
        print(f"client disconnected: id={client_id}; clients={len(CLIENTS)}", flush=True)

        
async def handler(ws) -> None:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(code=1008, reason="Expected a valid hello message")
        return

    msg_type = hello.get("type")
    if msg_type == "SOURCE_HELLO":
        await handle_source(ws, hello)
    elif msg_type == "CLIENT_HELLO":
        if NAIVE:
            await handle_client(ws, hello)
        else:
            await handle_client_new(ws, hello)
    else:
        await ws.close(code=1008, reason="Expected SOURCE_HELLO or CLIENT_HELLO")


# ---------------------------------------------------------------------------
# Monitoring / entry point
# ---------------------------------------------------------------------------
def print_queue() -> None:
    if NAIVE or not CLIENTS:
        return
    lens = [len(c) for c in CLIENTS]
    now = time.monotonic()
    print("[PROFILE_QUEUE_LENGTH]", "average", now,
          sum(lens) / len(lens), "max", max(lens), flush=True)
    if LAG_WINDOW_DROP:
        print("[PROFILE_LAG_DROPS]", now, LAG_DROPS, flush=True)
    if BATCH_FINALS:
        lagging = sum(1 for c in CLIENTS if c.lagging)
        print("[PROFILE_BATCH]", now, "lagging", lagging, "lag_entries", LAG_ENTRIES,
              "batches", BATCHES, "finals_batched", BATCHED_FINALS, flush=True)


async def monitor_fn(interval: float = 1.0) -> None:
    try:
        while True:
            print_queue()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        print("\nQueue monitor stopped.")


async def main_async(port: int) -> None:
    monitor_task = asyncio.create_task(monitor_fn(interval=1.0))
    async with websockets.serve(
        handler, "0.0.0.0", port,
        max_size=2**20, ping_interval=20, ping_timeout=20,
    ):
        print(f"LiveRecall v{VERSION} listening on ws://0.0.0.0:{port}", flush=True)
        await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()