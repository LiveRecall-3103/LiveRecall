# AI / Coding-Assistant Usage

## Tools used

List the generative-AI/coding tools used by the team and what each was used for.

## One useful suggestion

Describe one suggestion that materially helped the project and how you verified it.

## One suggestion that was wrong, inefficient, or required modification

Include a short generated suggestion/code fragment or precise description, explain the problem, and describe your correction.

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
