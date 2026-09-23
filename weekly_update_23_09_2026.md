# Weekly update — 23 September 2026

**In one line:** the 720-run study is complete on both applications, and this week we found that
its biggest apparent failure was our own plumbing, not a limit of kernel traces.

---

## 1. Where the study stands

Kernel traces only — no metrics, logs or spans. The agent is never told when the fault was, or
that there was one.

| | |
|---|---|
| applications | Sock Shop and Train Ticket |
| problems | 6 |
| runs | 3 incidents × 2 arms × 2 asks × 5 repeats = **60 per problem** |
| total | **720 runs, 0 failed** |
| model | `gpt-5.4-mini` |

Full reports: `blueprints/docs/SOCK-SHOP-RESULTS-22-09-2026.md` and
`blueprints/docs/TRAIN-TICKET-RESULTS-22-09-2026.md`, with charts.

### Results

**Sock Shop**

| problem | target | found WHERE | found WHEN |
|---|---|---|---|
| anomaly_cpu | host | 55/60 | 47/60 |
| anomaly_net | host | 50/60 | 20/60 |
| noisy_neighbor | host | 40/60 | 33/60 |
| slow_db | catalogue-db | 24/60 | 3/60 |
| svc_cpu_cap | carts | **1/60** | 49/60 |
| svc_net | carts | **0/60** | 39/60 |

**Train Ticket**

| problem | target | found WHERE | found WHEN |
|---|---|---|---|
| noisy_neighbor | host | 55/60 | 55/60 |
| anomaly_cpu | host | 54/60 | 51/60 |
| anomaly_net | host | 52/60 | 11/60 |
| slow_db | mysql | **3/60** | 32/60 |
| svc_cpu_cap | ts-travel-service | **0/60** | 15/60 |
| svc_net | ts-basic-service | **0/60** | 17/60 |

**The pattern is the same on both applications.** Host-wide faults are found 40–55 times out of
60. Faults inside one service are found 0–3 times out of 60.

That split replicating across two different codebases is the main result so far.

---

## 2. The main finding this week

We had been reading "0/60 on per-service faults" as *kernel traces cannot localise a fault to a
service*. **That reading was wrong.** Three separate pieces of our own plumbing were hiding the
answer.

### 2a. The reply cap was deleting the answer

Tool results were cut to 6000 characters with a plain string slice. Across all 720 transcripts,
11,189 tool calls:

- **every one of the 3,827 cut results was unparseable JSON**, chopped mid-number
- a prefix slice does not sample a result, it **deletes late fields entirely**

The tool that lists containers returns two lists. The second one reached the model in **4.7% of
742 calls**. Its usage notes reached it in **0%**.

That second list is where a container that was *already running* appears. An injected stress
process *spawns*, so it lands in the first list. The scores split exactly along that line:

| culprit | Sock Shop | Train Ticket |
|---|---|---|
| spawns | 55/60, 40/60 | 54/60, 55/60 |
| already running | 24, 1, 0 /60 | 3, 0, 0 /60 |

The cap was saving nothing — peak context use was **6.6%** of the model's window.

### 2b. The signal was always there

We then checked directly whether the per-service network fault is localisable at all. It injects
150 ms delay and 4% loss on one container's interface. Summing network events per container,
baseline against the true injection window:

| | injected container | median container | separation |
|---|---|---|---|
| Sock Shop, 3 runs | 0.155–0.184 of baseline | 0.63–0.73 | 3.8–4.1× |
| Train Ticket, 3 runs | 0.087–0.130 | 0.69–1.29 | 7.9–9.9× |

**Six of six, both applications.** One container's traffic collapses while everyone else's holds
steady. The signal is large, consistent, and sits in data the agent already had.

### 2c. Two more layers on top

- The **blueprint** reasoned only about network *interfaces*, and a kernel trace does not map an
  interface to a service. So it could say a path was impaired and never say whose.
- The **answer schema** asked for "a process name". The agent computed the right ranking in 6 of
  6 cells, saw the container, and then answered `java` — a name shared by several services here.

---

## 3. What we built

**Agent v2** — a plan / work / review / synthesise loop on LangGraph, with parallel workers.
The investigation method is v1's word for word, so the two differ in capability, not advice.

- **`run_python`** — the agent writes and runs its own analysis code. This removes the ceiling
  where it could only ask questions our six fixed tools could express.
- **Scratchpad** — workers record findings; the synthesiser reads those.
- **Planner and workers** — the investigation is split and run in parallel.

**The sandbox is the part worth reviewing.** Ground truth sits *inside* each run directory, so
code given a run path is one `open()` from the answer. It never sees a run path — only a
pre-loaded table. 19 adversarial escapes, all blocked, including two real holes the test caught:
counting file descriptors left room for exactly one open (it read `/etc/passwd`), and blocking
`open` is not enough because **pandas does its own file I/O**.

**Also rebuilt the trace index** for all 66 runs the next campaign needs, fixing two things:
raw lines were cut at 400 characters (the TCP header sits at ~660, so every sequence number was
past the cut), and the index counted events but never summed payloads (CPU nanoseconds, bytes,
disk sectors).

---

## 4. Does the new agent help?

Three arms, so we can separate "we fixed the tools" from "the agent got better". 48 cells each,
network problems, both applications.

| | v1 + old tools | v1 + fixed tools | v2 + fixed tools |
|---|---|---|---|
| SS svc_net, window accuracy | 0.543 | 0.569 | **0.776** |
| SS anomaly_net | 0.310 | 0.333 | **0.623** |
| TT svc_net | 0.262 | 0.311 | **0.559** |
| TT anomaly_net | 0.090 | 0.154 | 0.190 |

**The tool fixes bought speed** (334 s → 115 s per run). **The new agent roughly doubles how
accurately it finds WHEN**, on three of four.

Then, after fixing the blueprint and the answer format, on Sock Shop `svc_net`:

| | named the right container |
|---|---|
| before | 0 of 6 |
| + ranking step in the blueprint | 0 of 6 |
| + require the container id in the answer | **2 of 6** |

**The first non-zero localisation score on this problem in the whole study.** The two correct
answers name the injected container exactly. Of the two wrong ones, one names the database that
container talks to — the victim rather than the culprit.

**Caveat, stated plainly: n = 6.** Two runs out of six establishes direction and mechanism, not
size. It also holds for one application only — on Train Ticket 27 of 41 containers are
indistinguishable by CPU, so we cannot yet confirm which container is which there. That is
*unmeasurable*, not negative.

---

## 5. Things that were wrong and are now fixed

Worth listing because several would have been reported as findings.

| what | effect |
|---|---|
| reply cap sliced JSON | 3,827 unparseable tool results; the container list never arrived |
| raw lines cut at 400 chars | every TCP sequence number invisible |
| `ctf_lines` served filtered requests from a sample | asked for one process in a window holding 15,279 events, returned **0**, silently |
| pandas read `#` as a comment | the JVM names threads `GC Thread#7`; 23 million events vanished from Train Ticket analysis |
| two tools disagreed on the recording's end | one bucket, but they contradicted each other |
| scorer credited **any** container id as correct | would have produced a fake improvement — caught one commit before the run |
| `run_python` failed 80% of the time | 42% rejected for a harmless import, 38% killed by a thread limit |

**How they were found matters.** Most came from making two tools answer the same question and
comparing. Checking only that a tool returns something would have caught none of them.

---

## 6. Next steps

**Immediate**

1. **Re-run `svc_net` at full size** (5 repeats, n=30 per cell, both applications). This turns
   "2 of 6" into a number we can report. ~2 hours.
2. **Decide on cost before the full campaign.** v2 is 345k tokens per run against v1's 100k —
   3.5× for roughly double the window accuracy. At 1320 cells that is a real bill.

**Then**

3. **Apply the same treatment to `svc_cpu_cap`** — 1/60 and 0/60, the other big failure. The
   index now carries per-container CPU time, which is the equivalent measurement, but nothing has
   told the agent to rank on it yet.
4. **Run the full 11-problem matrix** with v2. Five new kernel-only blueprints landed this week
   (lock contention, deadlock, connection-pool exhaustion, dependency outage, priority
   inversion), taking the study from 6 problems to 11.
5. **Resolve container identity on Train Ticket.** Until we can say which container is which
   there, per-service results on that application cannot be verified either way.

**Open question for the team**

The study now has two axes, not one: does the *blueprint* help, and does *agent capability*
help. That is arguably a better paper than the blueprint axis alone — but it doubles the
campaign. Worth a decision before we commit the compute.

---

## Reference

| | |
|---|---|
| Results, Sock Shop | `blueprints/docs/SOCK-SHOP-RESULTS-22-09-2026.md` |
| Results, Train Ticket | `blueprints/docs/TRAIN-TICKET-RESULTS-22-09-2026.md` |
| When a blueprint makes an agent worse | `blueprints/docs/WHEN-A-BLUEPRINT-HURTS.md` |
| Daily decisions, with the reasoning | `progress-notes/22-09-2026/`, `progress-notes/23-09-2026/` |
| Data and results on Trillium | `/scratch/yuvraj17/stratatrace/results/q2-ss`, `q2-tt` |
| Agent v1 (produced the 720 runs) | git tag `agent-v1` |
