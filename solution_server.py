#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall server.

Versions (config.VERSION):
  0  naive broadcast
  2  per-client queue + ping flow control
  3  + lag-window disconnect
  4  + mass send: a lagging client receives all finals it lacks as ONE HISTORY
  5  + lookup at send time: a lagging client holds no queue; finals and the
       newest provisional are read from the store right before sending
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
BATCH_FINALS = VERSION >= 4            # opt 2
LOOKUP_WHEN_LAGGING = VERSION >= 5     # opt 3

MAX_LAG_WINDOW = 10.0   # s: oldest queued item older than this -> disconnect (V3)
LAG_ENTER = 1.0         # s: queue age / pong RTT / in-flight wait above this -> lagging
LAG_EXIT_AGE = 0.3      # s: (V4) queue age must fall below this ...
LAG_EXIT_RTT = 0.2      # s: ... and pong RTT below this -> back to full updates

# Counters for the report
LAG_DROPS = 0           # clients disconnected by the lag-window check
LAG_ENTRIES = 0         # times any client entered lag mode
BATCHES = 0             # mass sends
BATCHED_FINALS = 0      # finals delivered inside mass sends
LAG_ABSORBED = 0        # source updates not queued because the client was lagging (V5)
PROV_SENT_LAG = 0       # provisionals actually sent from store lookup (V5)


# ---------------------------------------------------------------------------
# Per-client state
# ---------------------------------------------------------------------------
class Slot:
    """One queued segment (newest revision only). Used in normal mode."""
    __slots__ = ("seg", "first_ts", "raw", "final", "alive")

    def __init__(self, seg: int, first_ts: float, raw: str, final: bool):
        self.seg = seg
        self.first_ts = first_ts    # when the segment first entered the queue (never reset)
        self.raw = raw
        self.final = final
        self.alive = True           # False = tombstone left in `order`


class Client:
    def __init__(self, ws, client_id, maxsize: int = 100):
        self.ws = ws
        self.client_id = client_id
        self.ready = asyncio.Event()
        self.maxsize = maxsize

        # ---- normal-mode queue (every revision, FIFO, coalesced per segment)
        self.initial: str | None = None       # late-join / resume HISTORY
        self.slots: dict[int, Slot] = {}      # segment -> live slot
        self.order: deque[Slot] = deque()     # FIFO, may hold tombstones

        # ---- cursors: O(1) state that replaces the queue while lagging
        # TCP is reliable and ordered, so "sent" == "will be received".
        self.last_final_sent = 0              # highest final segment sent
        self.last_prov = (0, 0)               # (segment, revision) last provisional sent in lag mode

        # ---- lag state
        self.rtt = 0.0                        # last send -> pong time
        self.inflight_since: float | None = None   # set while awaiting a send/pong
        self.lagging = False

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

    # ---- lag detection --------------------------------------------------------
    def maybe_enter_lag(self) -> None:
        """Cheap O(1) check, run on every enqueue and every send decision."""
        global LAG_ENTRIES
        if self.lagging:
            return
        now = time.monotonic()
        waiting = (now - self.inflight_since) if self.inflight_since is not None else 0.0
        if self.oldest_age(now) > LAG_ENTER or max(self.rtt, waiting) > LAG_ENTER:
            self.lagging = True
            LAG_ENTRIES += 1
            if LOOKUP_WHEN_LAGGING:
                self._clear_queue()           # the store now supplies everything

    # ---- producer side --------------------------------------------------------
    def set_initial(self, raw: str) -> None:
        self.initial = raw
        self.ready.set()

    def enqueue(self, segment: int, raw: str, final: bool = False) -> bool:
        """Queue one revision. Returns False if the client must be cut off."""
        global LAG_DROPS, LAG_ABSORBED

        if BATCH_FINALS:
            self.maybe_enter_lag()

        # V5 lag mode: the store is the source of truth. Keep NO per-client copy;
        # just wake the sender, which looks up the newest state right before sending.
        if LOOKUP_WHEN_LAGGING and self.lagging:
            LAG_ABSORBED += 1
            self.ready.set()
            return True

        slot = self.slots.get(segment)
        if slot is not None:
            if slot.final:
                return True                   # a final is never replaced
            slot.raw = raw                    # coalesce, keep original age
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

    # ---- consumer side: THE sending decision ------------------------------------
    def next_message(self, store: CaptionStore) -> str | None:
        """Called after the previous send AND its pong completed. Returns the next
        wire message, or None if there is nothing to send right now."""
        global BATCHES, BATCHED_FINALS, PROV_SENT_LAG

        # 1. Late-join / resume HISTORY always goes first, untouched.
        if self.initial is not None:
            raw, self.initial = self.initial, None
            return raw

        if not BATCH_FINALS:
            return self._pop_next()

        self.maybe_enter_lag()
        if not self.lagging:
            return self._pop_next()            # normal: every revision, in order

        # ---- lagging: decide from current state, not from queue order ----------
        # 2. Finals the client lacks (cursor vs the store's newest final).
        missing = store.finals_after_segment(self.last_final_sent)

        if len(missing) > 1:                   # gap -> ONE message for the whole gap
            self.last_final_sent = missing[-1].segment
            self._purge_sent_finals()          # V4 only has queued copies; V5 queue is empty
            BATCHES += 1
            BATCHED_FINALS += len(missing)
            # raws are already valid JSON objects: join instead of re-encoding
            return '{"type":"HISTORY","items":[' + ",".join(e.raw for e in missing) + "]}"

        if not LOOKUP_WHEN_LAGGING:
            # V4: the queue still exists. Leave lag mode once the client has caught up.
            if self.oldest_age() < LAG_EXIT_AGE and self.rtt < LAG_EXIT_RTT:
                self.lagging = False
            return self._pop_next()

        # ---- V5: pure store lookup ------------------------------------------------
        if missing:                            # exactly one final: send it as-is
            self.last_final_sent = missing[0].segment
            return missing[0].raw

        # 3. No finals missing: newest provisional, read NOW (never stored earlier),
        #    only for segments the client does not already hold a final for.
        prov = store.newest_active_after(self.last_final_sent)
        if prov is not None and (prov.segment, prov.revision) != self.last_prov:
            self.last_prov = (prov.segment, prov.revision)
            PROV_SENT_LAG += 1
            return prov.raw

        # 4. Fully caught up. If the client is responsive again, resume full updates.
        if self.rtt < LAG_EXIT_RTT:
            self.lagging = False
        return None                            # sender sleeps until the next enqueue

    # ---- internals ----------------------------------------------------------------
    def _pop_next(self) -> str | None:
        """Normal-mode FIFO. Skips finals already delivered inside a HISTORY batch."""
        while True:
            self._trim_order()
            if not self.order:
                return None
            slot = self.order.popleft()
            self._kill(slot)
            if slot.final:
                if BATCH_FINALS and slot.seg <= self.last_final_sent:
                    continue
                self.last_final_sent = max(self.last_final_sent, slot.seg)
            return slot.raw

    def _purge_sent_finals(self) -> None:
        for slot in [s for s in self.slots.values()
                     if s.final and s.seg <= self.last_final_sent]:
            self._kill(slot)

    def _clear_queue(self) -> None:
        for s in self.slots.values():
            s.alive = False
        self.slots.clear()
        self.order.clear()

    def _kill(self, slot: Slot) -> None:
        slot.alive = False
        del self.slots[slot.seg]

    def _trim_order(self) -> None:
        while self.order and not self.order[0].alive:
            self.order.popleft()

    def _maybe_compact(self) -> None:
        if len(self.order) > 2 * self.maxsize:     # bound tombstones
            self.order = deque(s for s in self.order if s.alive)


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
    """Enqueue into every client. No await inside, so store.apply and all enqueues
    happen with no task switch in between (a batch can't miss or double-send)."""
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
            client.ready.clear()               # clear BEFORE draining: a wake-up that
                                               # arrives mid-drain is never lost
            while True:
                msg = client.next_message(store)
                if msg is None:
                    break
                t0 = time.monotonic()
                client.inflight_since = t0     # lets lag detection see a stuck send
                await client.ws.send(msg)
                if PING_FLOW_CONTROL:
                    await (await client.ws.ping())
                client.rtt = time.monotonic() - t0
                client.inflight_since = None
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
    print("results      :", dict(stats))
    print("entries      :", len(store.entries))
    print("earliest     :", store.earliest, " latest:", store.latest)
    print("contig_final :", store.contig_final)
    print("lag entries  :", LAG_ENTRIES, " lag drops:", LAG_DROPS)
    print("batches      :", BATCHES, " finals in batches:", BATCHED_FINALS)
    print("lag absorbed :", LAG_ABSORBED, " provisionals sent from lookup:", PROV_SENT_LAG)


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

    # Everything below up to CLIENTS.add() is synchronous: no update can slip in
    # between the history snapshot and the client starting to receive live updates.
    history = store.get_history(last_segment, last_revision, history_seconds)
    raw = json.dumps({"type": "HISTORY", "items": [json.loads(e.raw) for e in history]})

    client = Client(ws=ws, client_id=client_id)
    # Cursor = newest final that exists right now. Finals up to here are either in
    # the HISTORY just built or deliberately outside the requested window; later
    # finals arrive live. So a later mass send never re-sends or over-sends.
    client.last_final_sent = max(max(0, last_segment), store.newest_final_seg())
    client.set_initial(raw)
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
        print("[PROFILE_BATCH]", now, "lagging", lagging, "batches", BATCHES,
              "finals_batched", BATCHED_FINALS, "absorbed", LAG_ABSORBED,
              "prov_sent_lag", PROV_SENT_LAG, flush=True)


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