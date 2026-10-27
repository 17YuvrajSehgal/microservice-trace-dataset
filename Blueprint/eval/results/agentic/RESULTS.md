# Results — matched-blueprint evaluation

Everything a results section needs, in one place. One section per (dataset × blueprint);
append new sections as more evaluations finish. Raw per-run rows live beside this file
(`<blueprint>/<run_id>/result.json`); machine-readable rollups in `<blueprint>/SCOREBOARD.json`.

## Common setup (applies to every section unless stated)

| | |
|---|---|
| research question | How often does the agent find the fault **when handed the correct blueprint** (matched arm)? Blueprint *selection* is a separate, later experiment. |
| agent | `Blueprint/agent/agent_v2.py` — LangGraph plan → 4 parallel workers → review (≤1 extra round) → synthesise. One worker is **deterministically dedicated to executing the blueprint's procedure** via `blueprint_tool`; the others keep exploratory breadth. Worker caps: 12 tool turns, 90 k-char thread budget. |
| evidence available to the agent | the kernel-trace count index (`bucket, event, procname, pid_ns, count, value_sum` at 100 ms) + raw-line sampling + the blueprint's own scripts (babeltrace-backed). **No metrics, no logs, no spans. Ground truth is unreachable by construction** — it is read only by the scorer. |
| model | `openai/gpt-6-luna` via OpenRouter (standard routing), temperature omitted |
| scoring | `Blueprint/eval/score.py`. **detected** = the committed `fault_type` carries the family's words (evidence prose is ignored — on clean runs evidence legitimately says "checked CPU, found nothing"). Controls: detected = the agent says normal / does not claim the fault. Agentic runs have no victim service (the cap is on the run's own cgroup), so WHERE is not scored there. |
| fairness | Blueprints were audited for answer leakage **before** these runs: the svc_mem_cap worked example had named the eval victim process (`ttmem`), its exact cap (768 M) and exact reclaim count; slow_db named "catalogue + MySQL + 500 ms" (the Sock Shop answer); svc_net named "a Java service". All anonymized to rough magnitudes with no names (commit `pre-run analysis fixes`). Results produced before that audit are invalid and were discarded. |
| reproduce | `cd Blueprint/eval && RCA_PROVIDER=openrouter RCA_MODEL=openai/gpt-6-luna ABL_WORKER_STEPS=12 ABL_THREAD_BUDGET=90000 python eval_matrix.py --problem <p> --runs-root <runs> --index-root index-agentic --out results/agentic/<p> --jobs 4` (resumable; scored cells are skipped) |

**Dataset (agentic):** OS-noise-for-agentic-AI runs — a real tool-using agent (Claude Code
2.1.296) executing coding tasks inside a cgroup on a 4-CPU GCP VM (kernel 7.0.0-gcp), LTTng
tracing the whole run. A "fault" is a cgroup limit set on the run's own cgroup; a "control" is
the same task uncapped. Ground truth per run = the limit in `meta/ground_truth.json` **plus the
cgroup's own counters** (`cpu.stat`, `memory.events` before/after), which independently record
whether the limit ever fired.

---

## 1. svc_cpu_cap × agentic (Claude) — COMPLETE 2026-10-22

**Design:** 42 runs = 31 faults (`cpu.max` ∈ {0.25, 0.5, 1.0} core on 4 CPUs; two task types) +
11 uncapped controls. Blueprint: `Blueprint/latency/1_svc_cpu_cap/README_v1.md` (10 tools).

### Headline

| metric | value |
|---|---|
| faults detected | **14 / 31** (45 %) |
| controls correct (no false alarm) | **11 / 11** (100 %) |
| detection on caps that bite hard (0.25 + 0.5 core) | **14 / 20** (70 %) |
| detection on mild caps (1.0 core) | 0 / 11 |

### By severity, with ground-truth bite

| `cpu.max` | runs | detected | nr_throttled per run (ground truth) | throttled time |
|---|---|---|---|---|
| 0.25 core | 10 | **8** | 134–219 episodes | ~20 s |
| 0.50 core | 10 | **6** | 57–106 | — |
| 1.00 core | 11 | 0 | 12–29 (brief) | — |
| uncapped | 11 | 11 said normal | 0 | 0 |

**Interpretation for the paper:** detection tracks how hard the cap bites. A 1-core cap on a
bursty, LLM-bound agent throttles only ~a dozen brief episodes per multi-minute run — the
scheduler wait-table barely moves, and the per-period ceiling is rarely pressed. The agent
reports "normal", which the raw metric counts as a miss but which is close to the kernel-trace
detectability floor for so mild a constraint. No false positives anywhere.

### Cost / effort (42 cells)

| | median | mean | total |
|---|---|---|---|
| wall clock / run | 379 s | 392 s (4 concurrent) | — |
| input tokens / run | 1.01 M | 0.98 M | 41.3 M |
| output tokens | — | — | 0.69 M |
| tool calls / run | 50 | — | — |
| cost | — | — | **$4.48** |

---

## 2. svc_mem_cap × agentic (Claude) — COMPLETE 2026-10-23

**Design:** 44 runs, all with a memory limit configured (`memory.high` soft or `memory.max`
hard, swept around the task's working set; no uncapped controls in this family — the uncapped
baseline lives in the cpu family). Blueprint: `Blueprint/latency/4_svc_mem_cap/README_v1.md`
(11 tools), **leak-free** (the worked example that previously named the victim process and the
exact cap was anonymized before this run).

### Headline

| metric | value |
|---|---|
| faults detected (raw, limit-configured = fault) | **25 / 44** (57 %) |
| **alignment with "cap actually bit"** (`memory.events` > 0) | **44 / 44 — 0 misses, 0 false positives** |

### By limit, with ground-truth bite

| limit | runs | detected | memory.events delta (ground truth) |
|---|---|---|---|
| high 768 M | 5 | **5** | ~9,300 `high` (reclaim) events |
| high 1152 M | 5 | **5** | ~8,500 `high` events |
| high 1536 M | 5 | 0 | **0 events — the limit never fired** |
| max 640 M | 3 | **3** | ~800 `max` + **1 OOM kill** each |
| max 768 M | 6 | **6** | ~18,600 `max` events |
| max 1024 M | 6 | **3** | bit in exactly 3 of 6 (~17,600 events); 0 in the other 3 |
| max 1280 M | 3 | **3** | ~8,300 `max` events |
| max 896 M | 3 | 0 | 0 events |
| max 2 G / high=max loose | 8 | 0 | 0 events |

### The headline claim this supports

> Per-run, the agent's verdict matched the cgroup's own counters **exactly**: it reported a
> memory cap in every run where `memory.events` shows the limit fired (reclaim, max, or OOM),
> and reported normal in every run where the configured limit never produced a single event.
> 44/44, with zero false positives — from the kernel trace alone, without access to the
> counters. The "misses" in the raw 25/44 are all runs whose limit demonstrably never bit;
> calling them normal is the correct reading of the system.

Combined with cpu — defining "bites" as substantial interference (cpu: quota ≤ 0.5 core,
57–219 throttle episodes/run; memory: any `memory.events` fired) and "no effect" as zero
events: **given the correct blueprint, detection is 39/45 (87 %) on faults that bite
(memory 25/25), and abstention is 30/30 where the configured fault produced no effect
(11 uncapped controls + 19 never-firing memory caps). The grey zone is the mild 1.0-core
cpu cap (0/11 detected, 12–29 brief episodes/run) — real but marginal interference at or
near the kernel-trace detectability floor.**

### Cost / effort (44 cells)

| | median | mean | total |
|---|---|---|---|
| wall clock / run | 267 s | 287 s (4 concurrent) | — |
| input tokens / run | 0.73 M | 0.75 M | 32.9 M |
| output tokens | — | — | 0.62 M |
| tool calls / run | 42 | — | — |
| cost | — | — | **$3.60** |

---

## 3. Microservice × 5 blueprints (Sock Shop + Train Ticket) — PARTIAL, 2026-10-27

**Dataset (microservice):** StrataTrace v2 on Trillium. Sock Shop (Go/Node/Java, ~15 containers)
and Train Ticket (Java/Spring, 60+ `ts-*` services), each under labeled fault injection with a
real victim *service* — so these score **WHERE** (the agent must name the victim container, via
`nsmap` pid_ns → service) and **window IoU**, which the agentic runs could not. 80 fault runs
(8+8+8+11+5 per app); `--jobs 6` on the Trillium **login** node (agent calls OpenRouter; compute
nodes have no internet). Same agent/model/scoring/budgets as §1–2 **except** worker caps raised
to 20 steps / 150 k budget — the microservice procedure (map → slice → sched_budget → victim →
ceiling across dozens of containers) needs more turns than the agentic one-cgroup case.

72 of 80 cells scored (8 lost to API rate-limits, resumable). Graded **by hand against ground
truth + the injection recipe** (`JUDGING.md`), not score.py — which under-counted badly by
demanding the gt `target_service` string and rejecting the aggressor/proxy/DB-peer the agent
correctly named. Per-run judgments: `results/<app>/JUDGMENTS*.md`.

### Sock Shop — the clean testbed (every fault `verification_status=confirmed`)

| blueprint | by-hand DETECTED | score.py said | localisation |
|---|---|---|---|
| svc_cpu_cap | **6/8** | 5/8 | cpu_throttling on `java` (carts); 2 runs hedged "other" = MISS |
| noisy_neighbor | **7/8** | 0/8 (pre-fix) | named aggressor `stress-ng`; 1 "normal" |
| slow_db | **8/11** | 1/11 | db_latency via `toxiproxy`/`mysqld`; caught 2/3 subtle-60 ms |
| svc_net | **5/5** | 5/5 | service_network on `java` (carts), netem 150 ms+4 % |
| svc_mem_cap | ⛔ n/a | — | trace has no memcg tracepoints (below) |

**Sock Shop headline: 26/32 = 81 % DETECTED** on the four evaluable blueprints, each with correct
localisation and a window overlapping the injection, on faults the dataset's own verification
confirms bit. Conservative grading throughout ("other"/"normal"/"unknown" = MISS). This is the
trustworthy microservice result.

### svc_mem_cap is NOT evaluable on microservice (data-collection gap, not a miss)

The Sock Shop / Train Ticket v2 trace profile recorded **425 event types — 377 syscall, 14
sched, 13 block, 10 net, 5 irq, 3 skb, 1 power — and zero memory events** (no `mm_vmscan_*`,
`memcg_reclaim`, `oom`, `kswapd`). The agentic profile *did* carry
`mm_vmscan_memcg_reclaim_begin/end`, which is exactly why agentic svc_mem_cap reached 44/44. The
memory-cap signature the blueprint reads — the memcg-reclaim burst — is **physically absent** from
these traces. The agent behaved correctly: it cut the right slices, found no reclaim, and
**declined to assert a memory cap** rather than inventing one. Marked not-evaluable and excluded
from totals; counting these as misses would falsify the result. Re-collecting with the memory
tracepoints enabled is future work.

### Train Ticket — a poor testbed (dataset, not the agent); hand-pass complete

Judged from the trace, not TT's unreliable metric labels (`JUDGMENTS-summary.md`). Only one TT
family produced a clear kernel-visible fault:

| blueprint | by-hand | why |
|---|---|---|
| **slow_db** | **4/8 DETECTED** | all 4 aggressive-500 ms caught (db_latency via toxiproxy / MySQL endpoint); missed 2 subtle-60 ms + 2 hedges. The one TT family that bit kernel-visibly. |
| svc_cpu_cap | not evaluable | caps did not bite — `ts-travel-service` idle (0.005 cores vs 0.2 cap), all 8 `unconfirmed`. Agent correctly said normal. |
| noisy_neighbor | not evaluable | 2–4 stress-ng workers on a 16-CPU host → host 63–84 % idle → no victim contention. Agent identified stress-ng (6/8) but correctly declined harm; r4 found the noisy container's own 2-core cap. Injection too weak. |
| svc_net | inconclusive | ts-basic-service traffic collapsed in-window (consistent with netem delay) but no retransmissions (`net_loss`: no TCP segments) amid 60 services' load swings. Agent read it as workload. Ambiguous; unconfirmed. |
| svc_mem_cap | not evaluable | no memcg tracepoints (same gap as Sock Shop). |

**Honest TT conclusion:** where TT's injection actually produced a kernel signature (aggressive
slow_db) the agent detected it **4/4**; everywhere else the fault either did not bite (cpu idle
service, noisy-neighbor too weak on 16 cores), is ambiguous (net collapse w/o retransmission), or
is not collectable (mem). This is a **Train Ticket v2 intensity/collection limitation**
(consistent with the documented `no_metric_signature` + re-collection notes), **not** an agent or
blueprint weakness. **Do not cite TT detection rates as agent performance** — the only citable TT
fact is: of TT injections with a clear kernel signature (aggressive slow_db), the agent got 4/4.

Cost so far: $11.4 for the 72 cells.

---

## Threats to validity / caveats (keep with any published number)

- **One model** (gpt-6-luna), one repeat per run (the grid itself carries 3–10 runs per level).
- **Matched arm only**: the correct blueprint is handed over; these numbers say nothing about
  blueprint *selection* (planned separately).
- Agentic runs score fault-type only (no WHERE): the cap is on the run's own cgroup, so there
  is no victim service to name. Microservice sections will add WHERE and window-IoU columns.
- The bite-alignment analysis uses the cgroup counters as ground truth; the agent never sees
  them (kernel trace only). The counters were collected per-run (`meta/*.before/after`).
- Mild-cap floor (cpu 1.0-core, 0/11): plausibly at/near the kernel-trace detectability floor
  (12–29 brief throttle episodes/run), but not proven impossible — a sharper per-period
  analysis might recover some.
- Earlier runs (before the leak audit + the dedicated blueprint worker + the CRLF tool fix)
  produced different numbers; they are invalid and deleted. The agent architecture changes that
  preceded THESE runs: one worker always executes the blueprint procedure; tool scripts fixed
  (CRLF, wrong-date self-heal); recording timespan shared once with all workers.

## Pending sections (same format, append below)

- [x] svc_cpu_cap / svc_net / noisy_neighbor × Sock Shop — **validated** (§3)
- [ ] svc_mem_cap + slow_db × Sock Shop — scored but blueprint misses; debugging (§3)
- [ ] all 5 × Train Ticket — scored but TT-wide issue; debugging (§3)
- [ ] microservice `normal`-run controls (specificity per blueprint)
- [ ] svc_cpu_cap + svc_mem_cap × agentic (Codex) — traces on Zenodo
- [ ] control arm (`--arm none`, no blueprint) for the blueprint-value comparison

### Note: does the host-scope scorer fix change the agentic numbers? No.

Re-scoring all 86 agentic cells with the post-fix scorer changed **0** of them (svc_cpu_cap
42/42 and svc_mem_cap 44/44 identical). The fix only fires when `truth["scope"] == "host"`;
agentic caps are `scope == "cgroup"`, so that branch never runs for them. §1–2 stand as-is.
