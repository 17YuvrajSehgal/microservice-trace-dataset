# Context pack — the dataset slide(s)

**For:** a Claude agent building the dataset slide for the M.Sc. abstract
presentation. Written 19 October 2026.

**Sources:** `blueprints/docs/DATASET-v2-INVENTORY.md` (microservice corpus),
`agentic-runs/` + `Blueprint/latency/1_svc_cpu_cap/agentic-os-noise/` (agentic
corpus). Run counts below were taken from the `manifest.csv` files on disk, not
from prose — see [How these numbers were checked](#how-these-numbers-were-checked).

**Rule:** every number here has a source. If it is not here and not in a source
file, it does not go on the slide. See [Numbers not to use](#numbers-not-to-use).

---

## 1. The single most important framing decision

**There are TWO corpora, not one.** They are different experiments serving
different parts of the thesis, and merging them into one number would be wrong.

| | **StrataTrace v2** | **The agentic OS-noise corpus** |
|---|---|---|
| What is observed | two microservice applications | two AI coding agents |
| Runs | **304** | **311** |
| Modalities | **four** (metrics, logs, distributed traces, kernel) | **kernel traces only**, deliberately |
| Faults | 27 families, injected into the app | 4 cgroup resource limits, imposed on the agent |
| Serves | the microservice leg of the thesis | the **agentic** leg — the agent as the system under observation |

> **Do not add 304 + 311 and call it one dataset.** They have different
> modalities, different subjects, and different purposes. The slide should
> present them as two panels, or as one slide plus one backup slide.

The sentence that ties them together:

> "Two corpora. One records a microservice system being broken on purpose. The
> other records an AI agent being starved of resources. **Both record the kernel
> layer that public incident datasets leave out.**"

---

## 2. Corpus A — StrataTrace v2 (the microservice dataset)

### Headline numbers

| | Sock Shop | Train Ticket | total |
|---|---|---|---|
| runs | 170 | 134 | **304** |
| all four modality directories present | 170/170 | 134/134 | **304/304** |
| kernel traces with **no event loss** | 170/170 | 133/134 | **303/304** |

- **27 fault families** plus a fault-free `normal` reference (28 recipes on Sock
  Shop, 21 on Train Ticket — three families are Sock-Shop-only).
- **Two applications**: Sock Shop (~16 services, polyglot) and Train Ticket
  (**47 services actually start, not 49** — two never come up; harmless, but a
  blueprint assuming a complete topology would be wrong about it).
- Collection finished **6 September 2026**, partly re-collected **15–17
  September**.
- **1.18 TB of bundles → 779 GB compressed** in 51 archives. The extracted
  working copy is **~8 TB**.
- Clocks aligned across modalities to **0.001 ms** drift.
- Every run carries a per-run Prometheus export of **~440 metric series**.

### Quality, measured rather than assumed

| | runs |
|---|---|
| **fully usable** | **293** |
| usable with a recorded caveat | 11 |
| not usable as a positive | **0** |

The test applied: all four modality directories, a loss-free kernel trace, the
fault demonstrably present, and a baseline that is a *reference* rather than a
second incident.

### The number that should be on the slide

**35 runs are `no_metric_signature`.**

That means: the fault is demonstrably present, and it was **measured** to have
no metric signature at all. For kernel-trace work those are the most valuable
runs in the set, not the weakest — they are precisely the cases where the
layer everyone else collects cannot see the problem.

Two concrete instances worth quoting:

- **`svc_net` on Train Ticket** — the metric target asked for a *decrease* in
  transmitted bytes, but packet loss causes retransmission and drives them
  **up** (15,938 → 31,517). The kernel trace measures **51.9–61.8%
  retransmission against a 0% baseline.**
- **`error_storm` on Train Ticket** — no usable metric exists (Spring services
  expose no actuator endpoint, and the node exporter reports its own network
  namespace). The evidence is in the **logs**: 462 "Communications link
  failure" and 1,078 SQLException, first line at the injection boundary,
  against **0** in a control run.

### A finding, not housekeeping — worth one line on the slide

**Six verification targets were corrected over 16–17 September.** The inventory
is explicit that this is a result:

> "**In every case the fault was real and the TARGET was wrong.**" The common
> flaw is targets that measure *consequences* — throughput, CPU usage, byte
> rates — which scale with offered load, instead of *mechanisms*, which do not.

Best example: `fd_exhaustion` went from **0/5 to 5/5** once scored correctly. Its
original target summed eleven Prometheus series that look like one, because
cAdvisor mints a new series per container restart — so a `decrease` target read
98 → 446. What the fault actually does is restart-loop the front-end, exactly
**9 times per injection**.

And `svc_cpu_cap` on Train Ticket went **0/8 to 8/8** by scoring the *mechanism*:
`container_spec_cpu_quota` does not exist until Docker applies a quota, so its
appearance *is* the fault. The old target watched CPU usage fall on a service
already idle at 0.00 cores.

### Per-family counts (if the slide wants a table)

5 repeats per family at aggressive/steady; intensity and workload studies add 3
more to selected families, which is why some read 8 or 11.

| family | SS | TT | | family | SS | TT |
|---|---|---|---|---|---|---|
| `normal` (reference) | 10 | 10 | | `lock_contention` | 5 | 5 |
| `anomaly_cpu` | 5 | 5 | | `priority_inversion` | 5 | 5 |
| `anomaly_disk` | 5 | 5 | | `deadlock` | 5 | 5 |
| `anomaly_mem` | 8 | 8 | | `fd_exhaustion` | 5 | 5 |
| `anomaly_net` | 8 | 8 | | `conn_pool_exhaustion` | 5 | 5 |
| `dependency_outage` | 5 | 5 | | `resource_abuse` | 5 | 5 |
| `error_storm` | 8 | 8 | | `data_exfiltration` | 5 | 5 |
| `noisy_neighbor` | 8 | 8 | | `fork_storm` | 5 | 5 |
| `queue_backlog` | 5 | — | | `nagle_delayed_ack` | 5 | 5 |
| `slow_db` | 11 | 11 | | `dns_delay` | 5 | — |
| `svc_cpu_cap` | 8 | 8 | | 5 × `code_*` | 25 | — |
| `svc_mem_cap` | 8 | 8 | | | | |
| `svc_net` | 5 | 5 | | | | |

**Coverage split:** 144 aggressive / 15 subtle / 10 none on Sock Shop;
109 / 15 / 10 on Train Ticket. 155 steady / 14 burst and 120 / 14 respectively.

### What one run contains

```
<run_id>/
  kernel/kernel/     CTF trace (LTTng)
  otlp/spans.jsonl   distributed traces, sliced to this run by byte offset
  logs/              per-container logs for the run window
  ust/               LTTng-UST relay — the cross-layer clock bridge
  meta/              clock anchors, enabled tracepoints, event_loss.json
  ground_truth.json  what was injected, when, with which parameters
  verification.json  the verdict, plus verification.as-collected.json
  MANIFEST.json      checksums, sizes
```

Each run is **60 s baseline · 120 s incident · 60 s recovery**, so every run
carries its own control window.

---

## 3. Corpus B — the agentic OS-noise corpus

This is the one that makes the **agentic** leg of the thesis real: the agent is
not only the consumer of the blueprint library, it is also the **system under
observation**.

### Headline numbers (counted from `manifest.csv`, not from prose)

| Campaign | Claude Code | Codex CLI | total |
|---|---|---|---|
| Problem 1 — CPU cap (`cpu.max`) | 40 | 40 | 80 |
| Problem 2 — threads vs cores, Part A | 20 | 20 | 40 |
| Problem 2 — sub-agents, Part B | 6 | 6 | 12 |
| Problem 3 — memory soft limit (`memory.high`) | 32 | 32 | 64 |
| Problem 3 — OOM cliff (`memory.max`) | 12 | 12 | 24 |
| Problem 4 — disk I/O cap (`io.max`) | 20 | 20 | 40 |
| **four-problem campaign** | **130** | **130** | **260** |
| end-to-end realistic coding task | 21 | 30 | **51** |
| **TOTAL** | **151** | **160** | **311** |

> **The paper abstract says "260 controlled runs."** That is the four-problem
> campaign only and **undercuts the real total**. Either say "260 across the
> four-problem campaign" (scoped, accurate) or "over 300 runs" (the full study).
> Do not say "260 runs" unqualified. This is flagged in the 15-10 progress note
> as the author's own call.

### The design

- **One VM**: 4 vCPU / 16 GB, Ubuntu 24.04, kernel 7.0.0-1011-gcp.
- **Kernel tracing only** (LTTng). **No metrics** — deliberately.
- **Two production agents**: Claude Code (Node) and Codex CLI (Rust, a different
  model over a different API). Every effect was replicated 1:1 across both.
- Each run: wipe and regenerate a **byte-identical** task repo, put the agent in
  a cgroup, set **exactly one** resource limit, record the full kernel trace plus
  the cgroup's own counters.
- **5 repeats per condition**, shuffled order, medians reported.
- **Ground truth comes from the kernel itself** — `cpu.stat`, `memory.events`,
  `memory.stat`, `io.stat`. Nothing is inferred.
- Trace-derived on-CPU time validated against `cpu.stat` to **97–99%**.
- Hypotheses **pre-registered** in each problem's `PLAN.md` before the runs.

### What it found (one line each, if the slide has room)

| Problem | Knob | Headline |
|---|---|---|
| CPU cap | `cpu.max` | a quarter core adds **+75%** wall time; the agent's compute stays fixed, it just waits |
| Threads vs cores | over-parallelism | 4× the core count adds **+295%**; the measured wait fraction matches the textbook `(W−C)/C` law to two decimals |
| Memory cap | `memory.high` / `memory.max` | **4.7× slower** on page-cache pressure, or **killed mid-task** on anonymous pressure — a sharp cliff between 640 MB and 768 MB |
| Disk I/O cap | `io.max` | **3.4× slower** at 50 MB/s; throttling is exact (1 GB in 20.4 s) |

The cross-cutting number: **~84% of the agent's wall time is model wait on a
healthy machine** (median over 10 runs, range 80–91%), while local computation
is only **~4.7 CPU-seconds**. Under a quarter-core cap that share falls to
**53%** — the OS takes the wall clock the model used to own.

### Why this corpus justifies kernel tracing in one sentence

> `cpu.stat` tells you *that* the cgroup was throttled and for how long. The
> wall clock says the run got slower. **Neither says what the agent was waiting
> on.** Counters measure *that* and *how much*; the trace measures *what* and
> *where*.

---

## 4. Why this dataset is novel — the comparison

Every public incident corpus stops at the application boundary.

| Dataset | Metrics | Logs | App traces | **Kernel** |
|---|---|---|---|---|
| RCAEval | ✓ | ✓ | ✓ | **✗** |
| LEMMA-RCA | ✓ | ✓ | ✓ | **✗** |
| OpenRCA | ✓ | ✓ | ✓ | **✗** |
| AIOps Challenge | ✓ | ✓ | ✓ | **✗** |
| MSDS | ✓ | ✓ | ✓ | **✗** |
| Nezha | ✓ | ✓ | ✓ | **✗** |
| LO2 | ✓ | ✓ | ✓ | **✗** |
| **StrataTrace v2** | ✓ | ✓ | ✓ | **✓** |

Live agent testbeds (AIOpsLab, ITBench) share the same boundary.

**The consequence, which is the real point:** a fault that lives below that line
— a co-tenant stealing CPU, a cgroup quota, a saturated disk — is outside both
the analysis *and its evaluation*. You cannot score a method on a fault your
data cannot see.

Also worth saying: **we have published on kernel traces before this**, so the
collection expertise is not new to the group.

---

## 5. Honest caveats — put at least two on the slide

A dataset slide that lists only strengths reads as marketing. These are
properties of the data, recorded deliberately.

**Three families are not the same experiment on the two applications.** Do not
compare them across applications without saying so:

- **`anomaly_disk`** — Train Ticket's own tracing writes ~176 MB/s of a 206 MB/s
  disk, so `stress-ng` adds only **+24 MB/s** there against **+80 MB/s** on Sock
  Shop. The instrument does not merely fail to see the fault; it **limits how
  large the fault can be**.
- **`svc_cpu_cap`** — `ts-travel-service` uses **0.0033 cores against a 0.2-core
  cap**, 60× headroom. The cap is genuinely applied, but it does not bite. Treat
  those runs as "the constraint was imposed", not "the service was starved".
- **`anomaly_net`** — no metric signature on Train Ticket at all, because netem
  adds *latency* and Train Ticket exposes no latency histogram.

**The observer effect, measured.** LTTng writes **~53 MB/s continuously** on
Sock Shop — exactly the measured baseline of `node_disk_written_bytes_total` —
so disk-time metrics sit near saturation before any fault starts. *Bounded
metrics are blind to faults our own collection contends for.* Use unbounded
counters for resource faults.

**One data loss, stated plainly.** **103 of 134 Train Ticket runs have no
client-side request CSV.** The cause was a load generator that only wrote its
rows after a thread pool joined with no timeout, so a cleanup trap killed it
with every row still in memory. Fixed 6 Sept. **The lost rows are not
recoverable** — they only ever existed in the killed process's memory. All four
modalities are complete in all 304 runs; this was a fifth artifact.

**One lossy run, kept on purpose.** `tt_anomaly_disk_aggressive_steady_r4` lost
~0.25% of its events. It is kept rather than hidden.

**A modality split worth a slide of its own if you have room.** Of the five
injected code defects, **two move a metric and three do not** — and the split is
**Node vs Go**. The two visible ones stall a single-threaded event loop; the
three invisible ones are Go, where concurrency absorbs a per-request slowdown
and throughput holds. *Same class of bug, opposite modality outcome.* Trace
volume agrees independently: 14–15 GB per visible family against 26–33 GB for
the invisible ones.

---

## 6. Numbers not to use

| Do not say | Why |
|---|---|
| a verdict breakdown that has to **sum** | `DATASET-v2-INVENTORY.md` has four arithmetic inconsistencies: the per-family table sums to 303 not 304; the verdicts table sums to 309; "fully usable by verdict" sums to 287 not 293; `no_metric_signature` reads 27 for TT in one table and 14 in another |
| "~24 fault families" | it is **27** plus a fault-free reference |
| "49 Train Ticket services" | **47** actually start |
| "260 runs" for the whole agentic study | that is the four-problem campaign; the full study is **311** |
| "<1% variation" for the agentic runs | disproven — wall time varies **10–15% from model noise alone** |
| "on-CPU matches `cpu.stat` to within 0.1–3%" | false. Median error **2.2%**, max **17.6%**, 17 of 40 runs over 3% |

**Safe formulation for the headline:** *"~304 runs — 170 Sock Shop + 134 Train
Ticket — 27 fault families, two applications, four modalities plus a per-run
metrics export."*

---

## 7. Suggested slide structure

### Option A — one slide (recommended for a 20-minute talk)

Split left/right.

- **Left: StrataTrace v2.** Five big numbers — `304 runs` · `27 fault families`
  · `4 modalities` · `0.001 ms` clock alignment · `779 GB`. Underneath, one
  line: *"35 runs were measured to have no metric signature at all — for
  kernel-trace work those are the most interesting runs in the set."*
- **Right: the agentic corpus.** `311 runs` · `2 coding agents` ·
  `4 cgroup limits` · `kernel traces only`. Underneath: *"the agent as the
  system under observation."*
- **Across the bottom:** the kernel column from the comparison table, as a
  single strip: *RCAEval ✗ · LEMMA-RCA ✗ · OpenRCA ✗ · AIOps ✗ · Nezha ✗ ·
  LO2 ✗ — **StrataTrace ✓***.
- **One caveat line**, so it does not read as marketing. The disk-instrument one
  is the most striking: *"Train Ticket's own tracing writes 176 MB/s of a
  206 MB/s disk — the instrument limits how large the disk fault can be."*

### Option B — two slides

Slide 1 is StrataTrace with the comparison table; slide 2 is the agentic corpus
with the four-problem table. Use this only if the dataset is a headline
contribution of the talk rather than supporting material.

### What to say out loud, not put on the slide

- The six corrected verification targets — *"in every case the fault was real
  and the target was wrong"*. It is the best one-line argument that the dataset
  was audited rather than assumed.
- The observer effect (`lttng-consumerd` and the 53 MB/s). It shows you measured
  your own instrument.

---

## 8. Where the data lives, and reproducibility

| | |
|---|---|
| StrataTrace v2 archives | Trillium `/scratch/yuvraj17/stratatrace/v2/{sockshop,trainticket}/` |
| working copy (extracted) | `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/<app>/<recipe>/<run_id>/` |
| Prometheus TSDBs | 362 MB (SS) + 582 MB (TT), taken with Prometheus **stopped** so the database is consistent |
| campaign logs | swept off both VMs before deletion — the driver's own narrative, which no run bundle carries |
| agentic corpus, code + metadata | in-repo under `agentic-runs/` and `Blueprint/latency/1_svc_cpu_cap/agentic-os-noise/`; raw traces gitignored to Trillium |
| agentic artifact repo | `C:/workplace/os-noise-for-agentic-ai` — code + every per-run `meta/` + `agent.log`, Zenodo DOI pending |

**Every collection VM has been deleted**, each only after its archives verified.
GCP cost for the project is zero. **Trillium holds the only copy of
StrataTrace v2.**

Two provenance points worth making if asked about rigour:

- The Prometheus snapshot preserves the **continuous** record — the gaps between
  runs, and cross-run baselines — which the per-run exports cannot reconstruct.
  Retention was the 15-day default, so it would have aged out regardless.
- Archive verification **decompresses every archive on the far side and counts
  runs**, rather than checksumming the stream, so a silently truncated archive
  cannot pass.

---

## How these numbers were checked

The agentic run counts in §3 were read from the `manifest.csv` in each run
directory on 19 Oct 2026, not copied from prose. Counting raw directories gives
slightly higher numbers (42 instead of 40 for Claude's CPU-cap set, 30 instead of
21 for the Claude end-to-end set) because smoke and profiling runs sit alongside
the campaign runs. **The manifests are the campaign record; use those.**

The StrataTrace numbers come from `blueprints/docs/DATASET-v2-INVENTORY.md`,
with the arithmetic inconsistencies noted in §6 rather than silently repeated.
