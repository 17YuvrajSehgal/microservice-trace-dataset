# StrataTrace demo

A local web app for showing what we built: one kernel trace, the blueprint that tells an agent
how to read it, and the agent's own investigation.

```
python demo/app.py            # then open http://127.0.0.1:8765
```

**Standard library only.** No pip install, no build step, no network, no API key. It runs from
a laptop with this repo and `demo/data/` present, which is the only thing that matters in a
meeting room.

First start does one pass over 4.1 million index rows (about 5 seconds) and caches the
aggregates. Every start after that is instant.

## The five tabs

| tab | what it shows |
|---|---|
| **Trace** | the recording: 243 s, 4.1M index rows, 373 event types, 21 containers. Pick an event and see its rate across the whole span. |
| **Discriminator** | the blueprint's deciding check, computed live. Drag on the chart to pick a suspect window and watch the ranking come out. |
| **Blueprints** | the library, and the full text of each one — the exact files handed to the agent. |
| **Agent** | the recorded investigation, played back step by step: plan, tool calls, the code it wrote, findings, verdict. |
| **Verdict** | its answer, then ground truth on demand. |

## What to show, in order

**1 · Trace.** Select `net_if_receive_skb`. The collapse and recovery are visible without any
analysis. Say: *the agent is not told any of this — not that an incident happened, not when.*

**2 · Discriminator.** This is the centre of the demo. Drag the middle of the chart.
`4026532538` comes out lowest at **0.109×** its own baseline against a median of 0.325× — a
**3× separation**, and an 89% drop against everyone else's 70-odd.

Then switch the **Signal** dropdown to *CPU time* or *scheduling*. Nothing separates. That is
the whole point: the impairment is on one container's network path, not the machine being busy,
and this is the distinction the blueprint exists to make.

**3 · Blueprints.** Open `network-path-degradation`. Scroll to *Investigation blueprint*, step 3
— the ranking the previous tab just ran, with the measured numbers behind it.

**4 · Agent.** Press **Run the agent**. It plans, writes and runs its own analysis code,
records findings, commits. Pause on a `code` step — that is the moment people react to.

**5 · Verdict.** Reveal ground truth. `pid_ns 4026532538` is `docker-compose_carts_1`, window
IoU 0.926.

**Then say the honest number, before anyone asks:** across 30 runs of this problem the agent
names the right container 10 times with the blueprint and once without.

## The trace

`svc_net_aggressive_steady_r3` — Sock Shop, 150 ms delay, 40 ms jitter, 4% packet loss on the
`carts` container's `eth0`, for 121 seconds.

The raw CTF trace is **15 GB**. What ships here is the **index**: counts per 100 ms bucket per
(event, process, container) plus one raw event line per bucket, built by a single decode of the
whole trace. That is what the agent's tools actually read. 37 MB, fetched by:

```
demo/fetch_data.sh          # needs the Trillium ssh alias
```

## Terminal version

If a browser is awkward, the same investigation replays in a terminal:

```
python blueprints/lib/demo_agent.py --step
```
