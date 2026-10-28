#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall naive working baseline.

This starter is intentionally useful but incomplete. It provides the required
CLI and a basic WebSocket broadcaster so that caption_source.py -> server ->
browser/load clients works on day one.

It DOES NOT implement the graded networking mechanisms:
  - revision-state management or deduplication
  - recent-history recovery or late-join recovery
  - bounded per-client application queues
  - slow-client isolation
  - semantic coalescing / backpressure
  - constrained-bandwidth overload handling

Required evaluator command:
    python solution_server.py --port 8765

Teams should replace or substantially extend the implementation while keeping
this command-line interface and the protocol in the assignment specification.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any
from collections import Counter

import time
import websockets

from config import VERSION
from server.store import CaptionStore, Entry, ACCEPTED

NAIVE = VERSION == 0
PING_FLOW_CONTROL = VERSION >= 2
LAG_WINDOW_DROP = VERSION >= 3
BATCH_FINALS = VERSION >= 4

MAX_LAG_WINDOW = 10.0   # s: oldest queued item older than this -> disconnect (V3)
LAG_ENTER = 1.0         # s: queue age or pong RTT above this -> lagging
LAG_EXIT_AGE = 0.3      # s: queue age must fall below this ...
LAG_EXIT_RTT = 0.2      # s: ... and pong RTT below this -> back to normal

# Performance counter: clients disconnected by the lag-window check (V3)
LAG_DROPS = 0

# Updated clients class
BATCHES = 0             # mass sends performed (V4)
BATCHED_FINALS = 0      # finals delivered inside those mass sends


# ---------------------------------------------------------------------------
# Per-client state
# ---------------------------------------------------------------------------
class Slot:
    """One queued segment (newest revision only)."""
    __slots__ = ("seg", "first_ts", "raw", "final", "alive")

    def __init__(self, seg: int, first_ts: float, raw: str, final: bool):
        self.seg = seg
        self.first_ts = first_ts    # when the segment first entered the queue
        self.raw = raw              # newest revision's JSON
        self.final = final
        self.alive = True           # False = tombstone left in `order`


class Client:
    def __init__(self, ws, client_id, maxsize: int = 100):
        self.ws = ws
        self.client_id = client_id
        # Used to eliminate HOL blocking
        # self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self.ready = asyncio.Event()
        self.maxsize = maxsize

        self.initial: str | None = None       # late-join / resume HISTORY
        self.slots: dict[int, Slot] = {}      # segment -> live slot (coalescing)
        self.order: deque[Slot] = deque()     # FIFO, may hold tombstones

        # Cursor: highest final segment already sent to this client.
        # TCP is reliable and ordered, so "sent" == "will be received".
        self.last_final_sent = 0

        # Lag state
        self.rtt = 0.0
        self.lagging = False
        
        self.last_prov = (0, 0)     # (segment, revision) of the last provisional sent in lag mode

    # ---- queries ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.slots) + (self.initial is not None)

    def oldest_age(self, now: float | None = None) -> float:
        self._trim_order()
        if not self.order:
            return 0.0
        if now is None:
            now = time.monotonic()
        return now - self.order[0].first_ts

    # ---- producer side --------------------------------------------------------
    def set_initial(self, raw: str, last_final: int) -> None:
        """Store the HISTORY reply and start the cursor at the newest final in it."""
        self.initial = raw
        self.last_final_sent = max(self.last_final_sent, last_final)
        self.ready.set()

    def enqueue(self, segment: int, raw: str, final: bool = False) -> bool:
        """Queue one revision. Returns False if the client must be cut off."""
        global LAG_DROPS
        # Lag mode: the store is the source of truth. Just wake the sender.
        if LOOKUP_WHEN_LAGGING and self.lagging:
            self.ready.set()
            return True
        slot = self.slots.get(segment)

        if slot is not None:
            if slot.final:
                return True                  # a final is never replaced
            slot.raw = raw                   # coalesce, keep original age
            slot.final = final
        else:
            if len(self.slots) >= self.maxsize:
                return False
            now = time.monotonic()
            if LAG_WINDOW_DROP and self.oldest_age(now) > MAX_LAG_WINDOW:
                LAG_DROPS += 1
                return False
            slot = Slot(segment, now, raw, final)
            self.slots[segment] = slot
            self.order.append(slot)
            self._maybe_compact()

        self.ready.set()
        return True

    # ---- lag detection --------------------------------------------------------
    def update_mode(self, store: CaptionStore) -> None:
        if not self.lagging:
            if self.oldest_age() > LAG_ENTER or self.rtt > LAG_ENTER:
                self.lagging = True
                if LOOKUP_WHEN_LAGGING:
                    self._clear_queue()          # store will supply everything
        else:
            # Leave only when the client is responsive AND has nothing outstanding,
            # otherwise the cleared queue would silently lose what it still lacks.
            if self.rtt < LAG_EXIT_RTT and self._nothing_missing(store):
                self.lagging = False

    # ---- consumer side: THE sending decision -----------------------------------
    def next_message(self, store: CaptionStore) -> str | None:
        global BATCHES, BATCHED_FINALS

        if self.initial is not None:
            raw, self.initial = self.initial, None
            return raw

        if not BATCH_FINALS:
            return self._pop_next()

        self.update_mode(store)

        if self.lagging and LOOKUP_WHEN_LAGGING:
            missing = store.finals_after_segment(self.last_final_sent)
            if len(missing) > 1:
                self.last_final_sent = missing[-1].segment
                BATCHES += 1
                BATCHED_FINALS += len(missing)
                return '{"type":"HISTORY","items":[' + ",".join(e.raw for e in missing) + "]}"
            if missing:
                self.last_final_sent = missing[0].segment
                return missing[0].raw
            prov = store.newest_active_after(self.last_final_sent)
            if prov is not None and (prov.segment, prov.revision) != self.last_prov:
                self.last_prov = (prov.segment, prov.revision)
                return prov.raw               # looked up now, not stored earlier
            return None                       # nothing new; sender sleeps until next enqueue

        return self._pop_next()

    # ---- internals --------------------------------------------------------------
    def _pop_next(self) -> str | None:
        while True:
            self._trim_order()
            if not self.order:
                return None
            slot = self.order.popleft()
            self._kill(slot)
            if slot.final:
                if BATCH_FINALS and slot.seg <= self.last_final_sent:
                    continue                 # already delivered inside a HISTORY batch
                self.last_final_sent = max(self.last_final_sent, slot.seg)
            return slot.raw

    def _purge_sent_finals(self) -> None:
        """After a mass send, kill queued finals the batch already covered.

        This shrinks the queue and lowers oldest_age so the client can leave
        lag mode once it catches up. Runs once per batch (queue <= maxsize).
        """
        for slot in [s for s in self.slots.values()
                     if s.final and s.seg <= self.last_final_sent]:
            self._kill(slot)

    def _kill(self, slot: Slot) -> None:
        slot.alive = False
        del self.slots[slot.seg]

    def _trim_order(self) -> None:
        while self.order and not self.order[0].alive:
            self.order.popleft()

    def _maybe_compact(self) -> None:
        if len(self.order) > 2 * self.maxsize:
            self.order = deque(s for s in self.order if s.alive)
            
        def _clear_queue(self) -> None:
        for s in self.slots.values():
            s.alive = False
        self.slots.clear()
        self.order.clear()

    def _nothing_missing(self, store: CaptionStore) -> bool:
        if store.finals_after_segment(self.last_final_sent):
            return False
        prov = store.newest_active_after(self.last_final_sent)
        return prov is None or (prov.segment, prov.revision) == self.last_prov


CLIENTS: set[Any] = set()

# Global caption store, shared by all source connections.
store = CaptionStore(keep_seconds=120.0, max_items=500)


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
async def broadcast_naively(raw_message: str) -> None:
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


async def broadcast(segment: int, raw_message: str, final: bool) -> None:
    """Put the message into every client's queue. Never awaits, so store.apply
    and this enqueue are atomic with respect to the sender tasks."""
    if not CLIENTS:
        return
    for client in list(CLIENTS):
        if not client.enqueue(segment, raw_message, final):
            CLIENTS.discard(client)
            asyncio.create_task(client.ws.close(code=1013, reason="client too slow"))


async def unicast(client: Client) -> None:
    try:
        while True:
            await client.ready.wait()
            while client:
                msg = client.next_message(store)
                if msg is None:
                    break
                await client.ws.send(msg)
                if PING_FLOW_CONTROL:
                    t0 = time.monotonic()
                    await (await client.ws.ping())
                    client.rtt = time.monotonic() - t0   # drives update_mode()
            client.ready.clear()
    except websockets.ConnectionClosed:
        pass


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
                        await broadcast(entry.segment, raw, entry.final)
            elif msg_type == "SOURCE_DONE":
                print("source finished", flush=True)
                dump_store(stats)
            else:
                continue
    finally:
        print("source disconnected", flush=True)


def dump_store(stats) -> None:
    print("---- store summary ----")
    print("results     :", dict(stats))
    print("entries     :", len(store.entries))
    print("earliest    :", store.earliest, " latest:", store.latest)
    print("contig_final:", store.contig_final)
    print("batches     :", BATCHES, " finals in batches:", BATCHED_FINALS)


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
    # Cursor starts at the newest final the client will hold after this HISTORY.
    newest = history[-1].segment if history else 0
    client.last_final_sent = max(0, last_segment)
    client.set_initial(raw, newest)
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
    lagging = sum(1 for c in CLIENTS if c.lagging)
    print("[PROFILE_QUEUE_LENGTH]", "average", time.monotonic(),
          sum(lens) / len(lens), "max", max(lens), flush=True)
    if LAG_WINDOW_DROP:
        print("[PROFILE_LAG_DROPS]", time.monotonic(), LAG_DROPS, flush=True)
    if BATCH_FINALS:
        print("[PROFILE_BATCH]", time.monotonic(), "lagging", lagging,
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