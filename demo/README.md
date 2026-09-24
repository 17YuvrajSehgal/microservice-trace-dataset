# StrataTrace demo

A local web app: one kernel trace, the blueprint that tells an agent how to read it, and the
agent **actually running on it**.

```
python demo/app.py            # then open http://127.0.0.1:8765
```

No build step. The server itself is standard library only. A live run additionally needs
`openai langgraph langchain-core pandas python-dotenv` and an API key in `.env` — the app
checks both on load and says plainly if it cannot run live.

## Two traces, chosen for opposite reasons

Pick from the dropdown in the header.

| trace | published | use it for |
|---|---|---|
| **Host CPU saturation** | 55/60 found the right component | the live run |
| **One service's network path** | 0/60 published, 10/30 after this week's fixes | the interesting conversation |

**Run the CPU one live.** Measured just now, twice: 133 s, names `stress-ng-cpu in pid_ns
4026533601`, window `08:14:06–08:16:06` against a true `08:14:06–08:16:07`, confidence 0.97.

**Do not run the network one live and hope.** It names the right container about a third of the
time. Two real runs while building this: one correct, one answered `host`. Use it to show the
Discriminator tab and to talk about why it is hard — and if you want to show a successful
network investigation, use **Replay**, and say it is a replay.

## The five tabs

| tab | what it shows |
|---|---|
| **Trace** | the recording: span, event types, containers, event rate across the whole run |
| **Discriminator** | the blueprint's deciding check, computed live on a window you drag out |
| **Blueprints** | the library, full text — the exact files handed to the agent |
| **Agent** | **Run the agent for real**, streamed as it happens, with **Stop**. Or replay a past run. |
| **Verdict** | its answer, then ground truth on demand |

## What to show, in order

**1 · Trace.** Pick an event. The fault is visible in the rate without any analysis. Say: *the
agent is told none of this.*

**2 · Discriminator.** Everything here follows the selected trace - the wording, the default
signal, and which blueprint is tagged.

On the **network** trace, drag the middle of the chart: `4026532538` comes out lowest at
**0.109×** its own baseline against a median of 0.325×. Switch **Signal** to CPU or scheduling
and nothing separates. That is the distinction the blueprint exists to make, watched rather
than asserted.

On the **CPU** trace the culprit goes the other way - `stress-ng-cpu` in `4026533601` has no
baseline at all and is flagged **appeared**. The tab reports both ends deliberately: ranking
only by the biggest faller was measured to find victims rather than the culprit, because when
one service stalls the whole application slows and everything else falls further.

**3 · Blueprints.** Open the one named on the Trace tab. Every check has a measurement behind
it; a validator rejects any that does not.

**4 · Agent — press Run the agent for real.** Two to four minutes. It plans, calls tools,
writes and runs its own analysis code, records findings, commits. What you are watching is the
audit record being written, not a narration built for the screen.

**Stop** cancels it at the next model call, usually within fifteen seconds. The partial
transcript stays on screen and is written to disk like any other run, so a stopped run is still
auditable. Useful if the room has seen enough, or if you want to talk over the first minute
rather than wait out all four.

Every tool call shows **asked** and **got back** - the arguments, then the few numbers that
came back. That is where the reasoning is visible: two `ctf_timeline` calls look identical
until you see one returned 25.3M events and the other 358k.

Two things worth pausing on when they appear:
- a **code** step — it wrote that itself, against the index in tab one
- the **evidence** in the verdict. On the CPU trace it typically says the late event-rate jump
  is *recovery, not onset*, and that runqueue-delay corroboration was attempted and was
  inconclusive. An agent stating what it could not verify is the point.

**5 · Verdict.** Reveal ground truth. It scores the run you just watched, using the study's
own scorer - not a demo copy, and not the recording's score.

**Every run is a new run.** Two measured back to back made 42 and 37 tool calls, wrote 3 and 6
snippets of code, and produced different plans. They open the same way because all four workers
independently call `ctf_timespan` first; the results underneath differ from there.

**Then say the honest rate before anyone asks.** Host-wide faults 40–55 of 60. Per-service
faults were 0–3 of 60 and are now 10/30 on the network one after this week's fixes.

## The data

The raw CTF traces are **15 GB each**. What ships is the **index** the agent's tools actually
read — counts per 100 ms bucket per (event, process, container), plus one raw event line per
bucket, from a single decode of the whole trace. ~37 MB per trace.

```
demo/fetch_data.sh          # needs the Trillium ssh alias
```

Ground truth lives in `demo/answer/`, deliberately **not** under the index root or the run
directory, so it is not sitting beside the data the code sandbox is handed.

## A note on the sandbox

The agent writes and runs its own code. On Linux it is confined by kernel limits — no writes,
capped memory, and a file-descriptor cap that stops pandas opening anything. Windows has no
`resource` module, so those are skipped; a guard on `open` inside the child takes over and
restricts it to the two index files. Every result reports `limits_enforced`, and
`agentic-rca/test_codetool.py` runs 19 escape attempts on either platform.

## Terminal version

```
python blueprints/lib/demo_agent.py --step
```
Replay only, no network. A fallback if the browser or the API is unavailable.
