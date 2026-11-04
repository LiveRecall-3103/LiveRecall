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

Describe one suggestion that materially helped the project and how you verified it.

## One suggestion that was wrong, inefficient, or required modification

Include a short generated suggestion/code fragment or precise description, explain the problem, and describe your correction.

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
