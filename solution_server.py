#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall server.

Versions:
  0: Naive broadcast
  2: Per-client queue + ping flow control
  3: + Lag-window disconnect
  4: + Batch missing finals into one HISTORY
  5: + Store lookup while lagging; no queue in lag mode
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
BATCH_FINALS = VERSION >= 4
LOOKUP_WHEN_LAGGING = VERSION >= 5

MAX_LAG_WINDOW = 10.0
LAG_ENTER = 0.3
LAG_EXIT_AGE = 0.3
LAG_EXIT_RTT = 0.2

# Experiment statistics
LAG_DROPS = 0
LAG_ENTRIES = 0
BATCHES = 0
BATCHED_FINALS = 0
LAG_ABSORBED = 0
PROV_SENT_LAG = 0

CLIENTS: set[Any] = set()
store = CaptionStore(keep_seconds=120.0, max_items=500)


class Slot:
    """One queued segment; provisional revisions replace the existing slot."""

    __slots__ = ("seg", "first_ts", "raw", "final", "alive")

    def __init__(self, seg: int, first_ts: float, raw: str, final: bool):
        self.seg = seg
        self.first_ts = first_ts
        self.raw = raw
        self.final = final
        self.alive = True


class Client:
    def __init__(self, ws, client_id, maxsize: int = 100):
        self.ws = ws
        self.client_id = client_id
        self.maxsize = maxsize
        self.ready = asyncio.Event()

        # Normal-mode queue
        self.initial: str | None = None
        self.slots: dict[int, Slot] = {}
        self.order: deque[Slot] = deque()

        # Delivery cursors
        self.last_final_sent = 0
        self.last_prov = (0, 0)

        # Flow control
        self.rtt = 0.0
        self.inflight_since: float | None = None
        self.lagging = False

    def __len__(self) -> int:
        return len(self.slots) + (self.initial is not None)

    def _trim_order(self) -> None:
        while self.order and not self.order[0].alive:
            self.order.popleft()

    def oldest_age(self, now: float | None = None) -> float:
        self._trim_order()
        if not self.order:
            return 0.0
        return (time.monotonic() if now is None else now) - self.order[0].first_ts

    def _kill(self, slot: Slot) -> None:
        slot.alive = False
        del self.slots[slot.seg]

    def _clear_queue(self) -> None:
        for slot in self.slots.values():
            slot.alive = False
        self.slots.clear()
        self.order.clear()

    def _maybe_compact(self) -> None:
        if len(self.order) > 2 * self.maxsize:
            self.order = deque(slot for slot in self.order if slot.alive)

    def _purge_sent_finals(self) -> None:
        for slot in list(self.slots.values()):
            if slot.final and slot.seg <= self.last_final_sent:
                self._kill(slot)

    def maybe_enter_lag(self) -> None:
        global LAG_ENTRIES

        if self.lagging:
            return

        now = time.monotonic()
        waiting = (
            now - self.inflight_since
            if self.inflight_since is not None
            else 0.0
        )

        if (
            self.oldest_age(now) > LAG_ENTER
            or max(self.rtt, waiting) > LAG_ENTER
        ):
            self.lagging = True
            LAG_ENTRIES += 1

            if LOOKUP_WHEN_LAGGING:
                self._clear_queue()

    def set_initial(self, raw: str) -> None:
        self.initial = raw
        self.ready.set()

    def enqueue(self, segment: int, raw: str, final: bool = False) -> bool:
        """Queue an update, or absorb it while V5 is lagging."""
        global LAG_DROPS, LAG_ABSORBED

        if BATCH_FINALS:
            self.maybe_enter_lag()

        if LOOKUP_WHEN_LAGGING and self.lagging:
            LAG_ABSORBED += 1
            self.ready.set()
            return True

        slot = self.slots.get(segment)

        if slot is not None:
            if slot.final:
                return True
            slot.raw = raw
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

    def _pop_next(self) -> str | None:
        """Pop the next live FIFO entry, skipping already-batched finals."""
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

    def _next_lagging_message(self, store: CaptionStore) -> str | None:
        """Deliver missing finals and, in V5, the newest unseen provisional."""
        global BATCHES, BATCHED_FINALS, PROV_SENT_LAG

        missing = store.finals_after_segment(self.last_final_sent)

        if len(missing) > 1:
            self.last_final_sent = missing[-1].segment
            self._purge_sent_finals()
            BATCHES += 1
            BATCHED_FINALS += len(missing)
            items = ",".join(entry.raw for entry in missing)
            return '{"type":"HISTORY","items":[' + items + "]}"

        if not LOOKUP_WHEN_LAGGING:
            if (
                self.oldest_age() < LAG_EXIT_AGE
                and self.rtt < LAG_EXIT_RTT
            ):
                self.lagging = False
            return self._pop_next()

        if missing:
            self.last_final_sent = missing[0].segment
            return missing[0].raw

        provisional = store.newest_active_after(self.last_final_sent)

        if (
            provisional is not None
            and (provisional.segment, provisional.revision) != self.last_prov
        ):
            self.last_prov = (provisional.segment, provisional.revision)
            PROV_SENT_LAG += 1
            return provisional.raw

        if self.rtt < LAG_EXIT_RTT:
            self.lagging = False

        return None

    def next_message(self, store: CaptionStore) -> str | None:
        """Select the next message after the previous send and pong complete."""
        if self.initial is not None:
            raw, self.initial = self.initial, None
            return raw

        if not BATCH_FINALS:
            return self._pop_next()

        self.maybe_enter_lag()

        if not self.lagging:
            return self._pop_next()

        return self._next_lagging_message(store)


async def broadcast_naively(raw_message: str) -> None:
    if not CLIENTS:
        return

    clients = list(CLIENTS)
    results = await asyncio.gather(
        *(client.send(raw_message) for client in clients),
        return_exceptions=True,
    )

    for client, result in zip(clients, results):
        if isinstance(result, Exception):
            CLIENTS.discard(client)


async def broadcast(segment: int, raw_message: str, final: bool) -> None:
    """Enqueue updates without yielding, preserving snapshot consistency."""
    for client in list(CLIENTS):
        if not client.enqueue(segment, raw_message, final):
            CLIENTS.discard(client)
            asyncio.create_task(
                client.ws.close(code=1013, reason="client too slow")
            )


async def unicast(client: Client) -> None:
    try:
        while True:
            await client.ready.wait()
            client.ready.clear()

            while True:
                message = client.next_message(store)
                if message is None:
                    break

                started = time.monotonic()
                client.inflight_since = started

                await client.ws.send(message)

                if PING_FLOW_CONTROL:
                    await (await client.ws.ping())

                client.rtt = time.monotonic() - started
                client.inflight_since = None

    except websockets.ConnectionClosed:
        pass


def parse_update(msg: dict, raw: str) -> Entry | None:
    try:
        seg = msg["segment"]
        rev = msg["revision"]
        final = msg["final"]
        ts = msg["source_ts"]
        text = msg["text"]
    except KeyError:
        return None

    if type(seg) is not int or type(rev) is not int or seg < 1 or rev < 1:
        return None
    if type(final) is not bool or not isinstance(text, str):
        return None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None

    return Entry(seg, rev, final, float(ts), text, raw)


async def handle_source(ws, hello: dict[str, Any]) -> None:
    print(f"source connected: session={hello.get('session')}", flush=True)
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

    finally:
        print("source disconnected", flush=True)


def dump_store(stats: Counter) -> None:
    print("---- store summary ----")
    print("results      :", dict(stats))
    print("entries      :", len(store.entries))
    print("earliest     :", store.earliest, " latest:", store.latest)
    print("contig_final :", store.contig_final)
    print("lag entries  :", LAG_ENTRIES, " lag drops:", LAG_DROPS)
    print("batches      :", BATCHES, " finals in batches:", BATCHED_FINALS)
    print(
        "lag absorbed :", LAG_ABSORBED,
        " provisionals sent from lookup:", PROV_SENT_LAG,
    )


async def handle_client(ws, hello: dict[str, Any]) -> None:
    """V0 naive client handler."""
    client_id = hello.get("client_id")
    await ws.send(json.dumps({"type": "HISTORY", "items": []}))
    CLIENTS.add(ws)

    print(
        f"client connected: id={client_id}; clients={len(CLIENTS)}",
        flush=True,
    )

    try:
        async for _ in ws:
            pass
    finally:
        CLIENTS.discard(ws)
        print(
            f"client disconnected: id={client_id}; clients={len(CLIENTS)}",
            flush=True,
        )


async def handle_client_new(ws, hello: dict[str, Any]) -> None:
    client_id = hello.get("client_id")

    try:
        last_segment = int(hello.get("last_segment", 0))
        last_revision = int(hello.get("last_revision", 0))
        history_seconds = max(
            0, min(int(hello.get("history_seconds", 30)), 60)
        )
    except (TypeError, ValueError):
        last_segment, last_revision, history_seconds = 0, 0, 30

    # No await between snapshot creation and registration: live updates cannot
    # slip between the history snapshot and registration.
    history = store.get_history(
        last_segment, last_revision, history_seconds
    )
    initial = json.dumps({
        "type": "HISTORY",
        "items": [json.loads(entry.raw) for entry in history],
    })

    client = Client(ws, client_id)
    client.last_final_sent = max(
        max(0, last_segment),
        store.newest_final_seg(),
    )
    client.set_initial(initial)

    CLIENTS.add(client)
    sender = asyncio.create_task(unicast(client))

    action = (
        "connected"
        if last_segment == 0 and last_revision == 0
        else "reconnected"
    )
    print(
        f"client {action}: id={client_id}; clients={len(CLIENTS)}",
        flush=True,
    )

    try:
        async for _ in ws:
            pass
    except websockets.ConnectionClosed:
        pass
    finally:
        sender.cancel()
        CLIENTS.discard(client)
        print(
            f"client disconnected: id={client_id}; clients={len(CLIENTS)}",
            flush=True,
        )


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
        await ws.close(
            code=1008,
            reason="Expected SOURCE_HELLO or CLIENT_HELLO",
        )


def print_queue() -> None:
    if NAIVE or not CLIENTS:
        return

    lengths = [len(client) for client in CLIENTS]
    now = time.monotonic()

    print(
        "[PROFILE_QUEUE_LENGTH]", "average", now,
        sum(lengths) / len(lengths), "max", max(lengths),
        flush=True,
    )

    if LAG_WINDOW_DROP:
        print("[PROFILE_LAG_DROPS]", now, LAG_DROPS, flush=True)

    if BATCH_FINALS:
        lagging = sum(client.lagging for client in CLIENTS)
        print(
            "[PROFILE_BATCH]", now,
            "lagging", lagging,
            "batches", BATCHES,
            "finals_batched", BATCHED_FINALS,
            "absorbed", LAG_ABSORBED,
            "prov_sent_lag", PROV_SENT_LAG,
            flush=True,
        )


async def monitor_fn(interval: float = 1.0) -> None:
    try:
        while True:
            print_queue()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        print("\nQueue monitor stopped.")


async def main_async(port: int) -> None:
    asyncio.create_task(monitor_fn())

    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=20,
    ):
        print(
            f"LiveRecall v{VERSION} listening on ws://0.0.0.0:{port}",
            flush=True,
        )
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