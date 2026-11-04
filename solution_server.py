#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall server.

v6: per-client queue + ping flow control + lag-window disconnect + lag mode
(finals first and unpaced, newest provisional only when idle) + drain-estimate
lag exit + event-driven pacing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from typing import Any

import websockets

from server.store import CaptionStore, Entry, ACCEPTED

MAX_LAG_WINDOW = 3.0    # s: normal-mode dirty age that disconnects (V3)

# ---- lag detection (pong based) ----
LAG_AGE_ENTER = 0.5      # s: sender stuck, dirty queue ageing -> lagging
PONG_WAIT = 1.0          # s: the sender never blocks on a pong longer than this
LAG_PONG_HARD = 1.0      # s: one pong this slow (or a timeout) -> lagging
LAG_PONG_SOFT = 0.2
PING_EVERY_N = 2

# ---- lag behaviour ----
LAG_PROV_GAP = 4.0       # s: while lagging, a provisional only after this long with no send
LAG_CALM_PONGS = 1       # fast pongs in a row needed before the exit estimate is consulted
LAG_QUEUE_GUESS = 32     # assumed size of the client library's receive queue (conservative)
LAG_EXIT_MARGIN = 2      # extra messages of drain required before leaving lag mode
IV_CAP = 1.0             # s: upper bound on the estimated client read interval

# Counters for the report
LAG_DROPS = 0
LAG_ENTRIES = 0
LAG_EXITS = 0


# ---------------------------------------------------------------------------
# Per-client state. The store holds the captions; the client holds cursors.
# ---------------------------------------------------------------------------
class Client:
    def __init__(self, ws, client_id, maxsize: int = 100):
        self.ws = ws
        self.client_id = client_id
        self.ready = asyncio.Event()
        self.maxsize = maxsize

        self.initial: str | None = None       # late-join / resume HISTORY (CLIENT_HELLO reply)
        self.dirty: dict[int, float] = {}     # normal mode: segment -> first_dirty_ts (FIFO)
        self.last_final_sent = 0              # cursor: highest final segment sent
        self.sent_rev: dict[int, int] = {}    # provisional segment -> highest revision sent

        self.rtt = 0.0
        self.soft_pongs = 0
        self.fast_pongs = 0

        self.lagging = False
        self.lag_since = 0.0
        self.lag_sent = 0                     # messages sent since entering lag mode
        self.iv_est = 0.5                     # estimated client read interval (s)

    # ---- queries ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.dirty) + (self.initial is not None)

    def oldest_age(self, now: float | None = None) -> float:
        if not self.dirty:
            return 0.0
        if now is None:
            now = time.monotonic()
        return now - next(iter(self.dirty.values()))

    def final_backlog(self, store: CaptionStore) -> bool:
        return store.newest_final_seg() > self.last_final_sent

    # ---- producer side --------------------------------------------------------
    def set_initial(self, raw: str, cursor: int) -> None:
        self.initial = raw
        self.last_final_sent = max(self.last_final_sent, cursor)
        self.ready.set()

    def enqueue(self, segment: int) -> bool:
        """Normal mode: mark the segment dirty (content is read from the store at
        send time). Lag mode: just wake the sender. False = cut the client off."""
        global LAG_DROPS
        self._maybe_enter_lag()
        if self.lagging:
            self.ready.set()
            return True
        if segment not in self.dirty:             # already dirty = coalesced, keep age
            if len(self.dirty) >= self.maxsize:
                return False
            now = time.monotonic()
            if self.oldest_age(now) > MAX_LAG_WINDOW:
                LAG_DROPS += 1
                return False
            self.dirty[segment] = now
        self.ready.set()
        return True

    # ---- lag detection ---------------------------------------------------------
    def _enter_lag(self, now: float, rtt: float) -> None:
        global LAG_ENTRIES
        if self.lagging:
            return
        self.lagging = True
        LAG_ENTRIES += 1
        self.lag_since = now
        self.lag_sent = 0
        self.fast_pongs = 0
        self.iv_est = min(max(rtt, 0.1), IV_CAP)
        self.dirty.clear()                        # store + cursor supply everything

    def _maybe_enter_lag(self) -> None:
        if not self.lagging and self.oldest_age() > LAG_AGE_ENTER:
            self._enter_lag(time.monotonic(), self.rtt)

    def on_pong(self, now: float, rtt: float, timed_out: bool) -> None:
        self.rtt = rtt
        if self.lagging and (timed_out or rtt > LAG_PONG_SOFT):
            # While the client's queue is full, a pong returns about one read interval
            # after the previous one. Keep the max: over-estimating is the safe direction.
            self.iv_est = min(max(self.iv_est, rtt), IV_CAP)
        if timed_out or rtt > LAG_PONG_HARD:
            self.fast_pongs = 0
            self._enter_lag(now, rtt)
        elif rtt > LAG_PONG_SOFT:
            self.fast_pongs = 0
            self.soft_pongs += 1
            if self.soft_pongs >= 1:
                self._enter_lag(now, rtt)
        else:
            self.soft_pongs = 0
            self.fast_pongs += 1

    def _caught_up(self, now: float) -> bool:
        if self.fast_pongs < LAG_CALM_PONGS:
            return False
        reads = (now - self.lag_since) / self.iv_est
        return reads - self.lag_sent >= LAG_QUEUE_GUESS + LAG_EXIT_MARGIN

    # ---- consumer side: the sending decision --------------------------------------
    def next_message(self, store: CaptionStore) -> str | None:
        global LAG_EXITS

        # 1. Late-join / resume HISTORY (reply to CLIENT_HELLO only).
        if self.initial is not None:
            raw, self.initial = self.initial, None
            return raw

        # Normal sending
        self._maybe_enter_lag()
        if not self.lagging:
            return self._next_fifo(store)

        # 2. Lag mode, finals first: one CAPTION_UPDATE each, oldest first, never paced.
        if self.final_backlog(store):
            missing = store.finals_after_segment(self.last_final_sent)
            if missing:
                e = missing[0]
                self.last_final_sent = e.segment
                self._forget_covered_revs()
                self.lag_sent += 1
                return e.raw

        # 3. Caught up? Return to full updates, seeding the segments in progress.
        now = time.monotonic()
        if self._caught_up(now):
            self.lagging = False
            self.soft_pongs = 0
            LAG_EXITS += 1
            for e in store.active_after(self.last_final_sent):
                self.dirty[e.segment] = now
            return self._next_fifo(store)

        # 4. Lag mode, provisional: only the NEWEST revision, only if the client lacks it.
        e = store.newest_active_after(self.last_final_sent)
        if e is not None and e.revision > self.sent_rev.get(e.segment, 0):
            self.sent_rev[e.segment] = e.revision
            self.lag_sent += 1
            return e.raw
        return None

    # ---- internals ----------------------------------------------------------------
    def _next_fifo(self, store: CaptionStore) -> str | None:
        """Normal mode: every revision, in order; content read from the store NOW."""
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
async def broadcast(segment: int) -> None:
    """Mark the segment dirty for every client. Never awaits."""
    if not CLIENTS:
        return
    for client in list(CLIENTS):
        if not client.enqueue(segment):
            CLIENTS.discard(client)
            asyncio.create_task(client.ws.close(code=1013, reason="client too slow"))


def _quiet(fut) -> None:
    """Retrieve the result of an abandoned pong future so asyncio doesn't warn."""
    if not fut.cancelled():
        fut.exception()


async def unicast(client: Client) -> None:
    last_send = 0.0
    pkt_ctr = 0
    try:
        while True:
            await client.ready.wait()
            while True:
                # Lag mode: provisionals are rationed, finals never wait. Sleep until
                # the gap expires or enqueue() wakes us (a final may have arrived).
                while client.lagging and not client.final_backlog(store):
                    wait = last_send + LAG_PROV_GAP - time.monotonic()
                    if wait <= 0:
                        break
                    client.ready.clear()
                    try:
                        await asyncio.wait_for(client.ready.wait(), timeout=wait)
                    except asyncio.TimeoutError:
                        break

                msg = client.next_message(store)         # chosen AFTER the wait
                if msg is None:
                    break
                t0 = time.monotonic()
                await client.ws.send(msg)
                last_send = t0
                pkt_ctr += 1
                if client.lagging and pkt_ctr % PING_EVERY_N != 0:
                    continue
                
                timed_out = False
                pong = await client.ws.ping()
                try:
                    await asyncio.wait_for(asyncio.shield(pong), timeout=PONG_WAIT)
                except asyncio.TimeoutError:
                    timed_out = True                     # never block the sender on a pong
                    pong.add_done_callback(_quiet)
                now = time.monotonic()
                client.on_pong(now, now - t0, timed_out)
            client.ready.clear()
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
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
                    await broadcast(entry.segment)
            elif msg_type == "SOURCE_DONE":
                # Test-control only: the server does not depend on it.
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
    print("lag entries  :", LAG_ENTRIES, " lag exits:", LAG_EXITS, " lag drops:", LAG_DROPS)
    print("unsent finals (id, gap):",
          [(c.client_id, store.newest_final_seg() - c.last_final_sent)
           for c in CLIENTS if c.lagging])


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------
async def handle_client(ws, hello: dict[str, Any]) -> None:
    client_id = hello.get("client_id")
    try:
        last_segment = int(hello.get("last_segment", 0))
        last_revision = int(hello.get("last_revision", 0))
        history_seconds = max(min(int(hello.get("history_seconds", 30)), 60), 0)
    except (TypeError, ValueError):
        last_segment, last_revision, history_seconds = 0, 0, 30

    # Synchronous from here to CLIENTS.add(): no update can slip in between the
    # history snapshot and the start of live delivery.
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
        await handle_client(ws, hello)
    else:
        await ws.close(code=1008, reason="Expected SOURCE_HELLO or CLIENT_HELLO")


# ---------------------------------------------------------------------------
# Monitoring / entry point
# ---------------------------------------------------------------------------
def print_queue() -> None:
    if not CLIENTS:
        return
    lens = [len(c) for c in CLIENTS]
    now = time.monotonic()
    print("[PROFILE_QUEUE_LENGTH]", "average", now,
          sum(lens) / len(lens), "max", max(lens), flush=True)
    print("[PROFILE_LAG_DROPS]", now, LAG_DROPS, flush=True)
    lagging = sum(1 for c in CLIENTS if c.lagging)
    print("[PROFILE_LAG]", now, "lagging", lagging, "entries", LAG_ENTRIES,
          "exits", LAG_EXITS, flush=True)


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
        print(f"LiveRecall v6 listening on ws://0.0.0.0:{port}", flush=True)
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