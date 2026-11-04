# AI / Coding-Assistant Usage

## Tools used

Our group used Claude as a coding assistant. We mainly used it to propose and refine ideas, and generate scripts to make testing easier and faster, and analyze failures of each test sets. 

The breakdown is as follows:
- Debugging
  - Finding why lagging client never left lag mode
- Designing and Trying flow control ideas:
  - Timed pings for lagging clients
  - `tc` based congestion detection
- Testing scripts:
  - Write some examples of hidden test cases to approximate the instructor's hidden test set
  - Write scripts (`run_private_tests.sh` and `run_public_tests.sh`) to mass run the test sets
  - Analyzing the failures of each test set to improve future iterations
- Documentation
  - Housekeeping of documentations

## One useful suggestion

**Suggestion:** Instead of queuing every raw message per client, keep one shared caption store and give each client only small cursors plus a "dirty" map (`segment -> first_dirty_timestamp`, in insertion order). The map acts as a FIFO of *segments*, not messages, and the content is read from the store at send time.

- **Coalescing:** a newer revision of an already-dirty segment adds no queue entry, so superseded provisional revisions are never sent.
- **Bounded by construction:** each client's queue is capped at a fixed number of segments rather than messages.
- **Ordering and no stale state:** a `last_final_sent` cursor stops a client from being sent a segment it already holds a final for, and a `sent_rev` map stops an older revision from being sent after a newer one.
- **Lag mode:** when a client falls behind, its dirty map is cleared. Finals are then sent oldest-first from the store using the cursor, and only the newest provisional revision is sent.

**Why it helped:** my first version stored each client's own copy of the data, and a final could be lost if a client was cut off. Keeping content in the shared store and only cursors per client means finals can always be recovered, and memory stays bounded because of the structure itself.

**How I verified it:** I ran `run_demo.py` with the public harness on different settings and checked that final-caption completeness stayed at the expected level, there were no duplicate or stale messages, and server memory stayed flat. Results improved slightly compared with the earlier version. 

I did not record measurements for the old per-client-copy version, so I can't give a before/after comparison.

**How I built on it:** I adopted the suggested structure largely as proposed. My own additions were in the ping/pong handling on top of it: using pong round-trip time to decide when a client enters and leaves lag mode, and pacing sends by waiting on pongs.
`

## One suggestion that was wrong, inefficient, or required modification

Solution that AI suggested is to add a fixed pinger every 2 seconds.
```
LAG_PING_GAP = 2.0   # s: lagging clients ping at most this often (saves bandwidth for finals)

async def unicast(client: Client) -> None:
    last_send = 0.0
    last_ping = 0.0                                   # new
    ...
                t0 = time.monotonic()
                await client.ws.send(msg)
                last_send = t0
                if PING_FLOW_CONTROL and (not client.lagging or t0 - last_ping >= LAG_PING_GAP):
                    last_ping = t0
                    timed_out = False
                    pong = await client.ws.ping()
                    try:
                        await asyncio.wait_for(asyncio.shield(pong), timeout=PONG_WAIT)
                    except asyncio.TimeoutError:
                        timed_out = True
                        pong.add_done_callback(_quiet)
                    now = time.monotonic()
                    client.on_pong(now, now - t0, timed_out) 
```
This is not good because the timer will send regardless of how slow the bandwidth is. Suppose the bandwidth is so low that it can only support 1 message every 2 seconds, then the whole channel will be flooded with the ping messages only. A better way would be to send a ping after every 4 if the client is lagging, and send after every 1 packet for normal conditions. This would adapt to the network conditions.

## Responsibility statement

We understand that the team remains responsible for the submitted code, experimental results, and claims, and that every member may be asked to explain or modify relevant code during the viva.
