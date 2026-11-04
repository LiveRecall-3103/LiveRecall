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

- **Report formatting:** We used AI to help format the report (Markdown structure, tables, figure captions and layout). The team wrote and checked all the technical content.
- **Graph data analysis:** We used AI to help analyse the experiment data behind our graphs, such as summarising trends and comparing results across versions. We checked every number and conclusion against the raw test outputs before putting it in the report.

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

**Suggestion.** Limit pings for lagging clients by time: at most one ping every 2 s.

```python
LAG_PING_GAP = 2.0
...
await client.ws.send(msg)
if not client.lagging or t0 - last_ping >= LAG_PING_GAP:
    last_ping = t0
    pong = await client.ws.ping()   # sender waits for the pong (up to PONG_WAIT = 1 s)
```

**Problem.** A time limit doesn't adapt to link speed. If the link carries one message every 2 s, the gap has always passed, so every message still gets a ping and the sender still waits on each pong. Lag mode saves nothing on the slow links it is meant for.

**Correction.** Count messages instead of time: ping after every message normally, and after every 2nd message when lagging, so ping cost scales with what actually gets through.

```python
pkt_ctr += 1
if client.lagging and pkt_ctr % PING_EVERY_N != 0:   # PING_EVERY_N = 2
    continue                                         # skip this ping
pong = await client.ws.ping()
```

## Responsibility statement

We understand that the team remains responsible for the submitted code, experimental results, and claims, and that every member may be asked to explain or modify relevant code during the viva.
