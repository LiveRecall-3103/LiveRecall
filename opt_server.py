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
from collections import deque
from dataclasses import dataclass
from typing import Any
from collections import Counter

import websockets

NAIVE = False

# Implemented by Claude: ping-based flow control.
# At most SEND_WINDOW messages may be sent to a client without being
# confirmed by a pong. A client only answers a ping after reading everything
# sent before it, so a slow client stops getting new sends and its backlog
# stays in our per-client queue, where newer revisions replace older ones
# (see Client.enqueue). Fast clients answer within milliseconds, so they
# still receive every revision.
SEND_WINDOW = 4

# Updated clients class
class Client:
    def __init__(self, ws, client_id, maxsize: int=100):
        self.ws = ws
        self.client_id = client_id
        # Used to eliminate HOL blocking
        # self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self.ready = asyncio.Event()
        self.maxsize = maxsize
        self.order = deque()
        self.pending: dict[int, str] = {}
        # Implemented by Claude: flow-control state.
        self.unacked = 0    # messages sent but not yet confirmed by a pong
        self.lag = 0.0      # seconds the last pong took (useful for logging)

    def enqueue(self, segment, raw) -> bool:
        if segment in self.pending:
            self.pending[segment] = raw
        else:
            if len(self.order) == self.maxsize:
                return False
            else:
                self.order.append(segment)
                self.pending.update({segment:raw})

        self.ready.set()
        return True

    def dequeue(self) -> str:
        segment = self.order.popleft()
        msg = self.pending.pop(segment)
        return msg
    
CLIENTS: set[Any] | set[Client] = set()
from server.store import CaptionStore, Entry, ACCEPTED
# Global caption store, used by all source connections. 
store = CaptionStore(keep_seconds=120.0, max_items=500)

async def broadcast_naively(raw_message: str) -> None:
    """Send one message directly to every connected client.

    This is intentionally a naive baseline. The source handler waits for all
    sends to complete. Under pressure, this design may accumulate delay and is
    not the target architecture for the assignment.
    """
    
    # Testing for Source - Server
    print("broadcasting to %d clients: %s", len(CLIENTS), raw_message, flush=True)
    
    
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

async def broadcast(segment, raw_message: str) -> None:
    """
    Put the message into all clients' queue.
    """
    if not CLIENTS:
        return

    snapshot = list(CLIENTS)

    # Claude: suggested me to drop connection if client is too weak
    # 
    # Client to re-establish a connection to prevent client queue from
    # getting too big
    for client in snapshot:
        if not client.enqueue(segment, raw_message):
            CLIENTS.discard(client)
            asyncio.create_task(client.ws.close(code=1013, reason="client too slow"))

def _on_pong(client, count: int, fut) -> None:
    """Implemented by Claude: the client has read `count` more messages."""
    if fut.cancelled() or fut.exception() is not None:
        return  # connection closed; handle_client_new cleans up
    client.unacked -= count
    client.lag = fut.result()
    client.ready.set()  # wake unicast: the window has room again

async def unicast(client) -> None:
    # Implemented by Claude: send while the window has room, then ping.
    # The pong callback frees the window and wakes this loop again.
    try:
        while True:
            await client.ready.wait()
            client.ready.clear()  # clear first so a wake-up during send isn't lost
            sent = 0
            while client.order and client.unacked < SEND_WINDOW:
                await client.ws.send(client.dequeue())
                client.unacked += 1
                sent += 1
            if sent:
                pong = await client.ws.ping()
                pong.add_done_callback(
                    lambda fut, n=sent: _on_pong(client, n, fut))
    except websockets.ConnectionClosed:
        pass

# ---- message parsing for source updates ------------------------------------------------------
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
                print(f"  seg {entry.segment:>3} rev {entry.revision} "
                      f"{'FINAL' if entry.final else 'draft'} -> {result}", flush=True)
                if result == ACCEPTED:
                    if NAIVE:
                        await broadcast_naively(raw)      # temporary, as before
                    else:
                        await broadcast(entry.segment, raw)

            elif msg_type == "SOURCE_DONE":
                # Test-control message. The specification does not require it
                # to be forwarded to clients.
                print("source finished", flush=True)
                dump_store(stats)
            else:
                # Forward compatibility: ignore fields/messages this baseline
                # doesn't understand rather than crashing.
                continue
    finally:
        print("source disconnected", flush=True)


def dump_store(stats):
    print("---- store summary ----")
    print("results     :", dict(stats))
    print("entries     :", len(store.entries))
    print("earliest    :", store.earliest, " latest:", store.latest)
    print("contig_final:", store.contig_final)
    print("active      :", [e.segment for e in store.active()])
    for s in store.order:
        e = store.entries[s]
        print(f"  seg {s:>3} rev {e.revision} {'FINAL' if e.final else 'draft'} ts={e.source_ts:.3f} {e.text[:40]!r}")
        
"""
Handle client's connection to the server for the whole connection, including
resuming connection state.
"""        
async def handle_client(ws, hello: dict[str, Any]) -> None:
    client_id = hello.get("client_id")

    # The baseline has no stored recovery state. Sending an empty HISTORY makes
    # the connection behavior visible and keeps the starter easy to inspect.
    # Students must implement correct HISTORY semantics for the assignment.

    # naive: just keep sending latest segment
    await ws.send(json.dumps({"type": "HISTORY", "items": []}))

    CLIENTS.add(ws)
    print(f"client connected: id={client_id}; clients={len(CLIENTS)}", flush=True)
    try:
        # Student clients normally don't send further messages after hello.
        # Keep the WebSocket open until the client disconnects.
        async for _ in ws:
            pass
    finally:
        CLIENTS.discard(ws)
        print(f"client disconnected: id={client_id}; clients={len(CLIENTS)}", flush=True)

"""
Checks if a client has been connected before.

If yes, it will send based on the information like the last segment and rev,
and for how long does the client want to receive. (Whole segment is received)
!!! Client should make sure to check its own buffer for how long does it store
instead of keep on requesting.

If no, it will add the client to the CLIENTS list and return the past 30 seconds
worth of transcriptions.

Vulnerability: Only validates client_id, vulnerable to spoofing
TODO: deduplicate client_id
"""
async def handle_client_new(ws, hello: dict[str, Any]) -> None:
    # format hello message
    client_id = hello.get("client_id")
    session = hello.get("session") # not used
    last_segment = int(hello.get("last_segment", 0))
    last_revision = int(hello.get("last_revision", 0))
    history_seconds = max(min(int(hello.get("history_seconds", 30)), 60), 0)

    history = store.get_history(last_segment, last_revision, history_seconds)
    raw = json.dumps({
                        "type": "HISTORY",
                        "items": [json.loads(e.raw) for e in history],
                    })
    
    client = Client(ws=ws, client_id=client_id)
    client.enqueue(-1, raw)
    CLIENTS.add(client)
    sender = asyncio.create_task(unicast(client))
    
    if last_segment == 0 and last_revision == 0:
        print(f"client connected: id={client_id}; clients={len(CLIENTS)}", flush=True)
    else:
        print(f"client reconnected: id={client_id}; clients={len(CLIENTS)}", flush=True)

    try:
        async for _ in ws:
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


async def main_async(port: int) -> None:
    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=20,
    ):
        print(f"LiveRecall baseline listening on ws://0.0.0.0:{port}", flush=True)
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
