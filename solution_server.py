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

import websockets

NAIVE = True

# Updated clients class
class Client:
    def __init__(self, ws, client_id, maxsize: int=100):
        self.ws = ws
        self.client_id = client_id
        # Used to eliminate HOL blocking
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)

# Placeholder class Entry and CaptionStore to be replaced by Jimmy's real class
@dataclass
class Entry:
    segment: int
    revision: int
    final: bool
    source_ts: float
    text: str
    raw: str    

class CaptionStore:
    def init(self, keep_seconds: float = 90.0, max_items: int = 500):
        self.keep_seconds = keep_seconds
        self.max_items = max_items            # hard cap, in case timestamps misbehave
        self.entries: dict[int, Entry] = {}   # segment -> newest Entry
        self.order: deque[int] = deque()      # segment numbers, ascending
        self.latest_ts = 0.0                  # newest source_ts seen
        self.contig_final = 0                 # highest N where segments 1..N are al

    def get_history(self, last_segment=0, last_revision=0, history_seconds=30) -> list[Entry]:
        return
# End of placeholder code

# Naive global set of currently connected student clients.
# There is deliberately no per-client queue or recovery state here.
CLIENTS: set[Any] | set[Client] = set()
db = CaptionStore()

async def broadcast_naively(raw_message: str) -> None:
    """Send one message directly to every connected client.

    This is intentionally a naive baseline. The source handler waits for all
    sends to complete. Under pressure, this design may accumulate delay and is
    not the target architecture for the assignment.
    """
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

async def broadcast(raw_message: str) -> None:
    """
    Put the message into all clients' queue.
    """
    if not CLIENTS:
        return

    snapshot = list(CLIENTS)

    for client in snapshot:
        client.queue.put_nowait(raw_message)

async def unicast(client) -> None:
    try:
        while True:
            msg = await client.queue.get()
            await client.ws.send(msg)
    except websockets.ConnectionClosed:
        pass

async def handle_source(ws, hello: dict[str, Any]) -> None:
    session = hello.get("session")
    print(f"source connected: session={session}", flush=True)

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "CAPTION_UPDATE":
                # Baseline behavior: forward exactly what was received.
                # No history, state, validation, coalescing, or bounded queues.
                if NAIVE:
                    await broadcast_naively(raw)
                else:
                    await broadcast(raw)
            elif msg_type == "SOURCE_DONE":
                # Test-control message. The specification does not require it
                # to be forwarded to clients.
                print("source finished", flush=True)
            else:
                # Forward compatibility: ignore fields/messages this baseline
                # doesn't understand rather than crashing.
                continue
    finally:
        print("source disconnected", flush=True)

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
    history = db.get_history(last_segment, last_revision, history_seconds)
    history_msg = json.dumps({
                "type": "HISTORY",
                "items": [json.loads(entry.raw) for entry in (history or [])],
            })
    
    client = Client(ws=ws, client_id=client_id)
    client.queue.put_nowait(history_msg)
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
