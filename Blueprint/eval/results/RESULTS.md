# Results — matched-blueprint evaluation

Everything a results section needs, in one place. One section per (dataset × blueprint);
append new sections as more evaluations finish. Raw per-run rows live beside this file
(`<blueprint>/<run_id>/result.json`); machine-readable rollups in `<blueprint>/SCOREBOARD.json`.

## Common setup (applies to every section unless stated)

| | |
|---|---|
| research question | How often does the agent find the fault **when handed the correct blueprint** (matched arm)? Blueprint *selection* is a separate, later experiment. |
| agent | `../../agent/agent_v2.py` — LangGraph plan → 4 parallel workers → review (≤1 extra round) → synthesise. One worker is **deterministically dedicated to executing the blueprint's procedure** via `blueprint_tool`; the others keep exploratory breadth. Worker caps: 12 tool turns, 90 k-char thread budget. |
| evidence available to the agent | the kernel-trace count index (`bucket, event, procname, pid_ns, count, value_sum` at 100 ms) + raw-line sampling + the blueprint's own scripts (babeltrace-backed). **No metrics, no logs, no spans. Ground truth is unreachable by construction** — it is read only by the scorer. |
| model | `openai/gpt-6-luna` via OpenRouter (standard routing), temperature omitted |
| scoring | **Agentic (§1–2):** `../score.py` — **detected** = the committed `fault_type` carries the family's words. **Microservice (§3):** graded **by hand** against ground truth + the injection recipe (`../JUDGING.md`), because score.py's keyword/target-string matching mis-scored both ways (it rejected the aggressor/proxy the agent correctly named). Conservative: "other"/"normal"/"unknown" on a real fault = MISS; naming the aggressor/proxy/DB-peer the recipe used = correct WHERE. |
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
11 uncapped controls. Blueprint: `../../latency/1_svc_cpu_cap/README_v1.md` (10 tools).

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
baseline lives in the cpu family). Blueprint: `../../latency/4_svc_mem_cap/README_v1.md`
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

Two passes, same model, graded by hand:
- **v1** — original blueprints.
- **v2** — after fixing the three miss root causes found by RCA (commit `6992bc3`): `cpu_ceiling`
  judges a cap by collapse-vs-baseline + runnable-wait + idle CPUs instead of flatness; the
  noisy blueprint forces the decisive `cpu_hogs` check before any verdict; slow_db takes its
  baseline from a verified-quiet stretch outside the incident window. All three fixes are general
  (no hardcoded service names / quotas / thresholds).

| blueprint | v1 DETECTED | **v2 DETECTED (fixed)** | localisation |
|---|---|---|---|
| svc_cpu_cap | 6/8 | **7/8** | cpu_throttling on `java` (carts); v1 misses r3,r5 **recovered**; 1 different cell (subtle_r2) hedged "other" |
| noisy_neighbor | 7/8 | **7/7** (r2 rate-limited) | named aggressor `stress-ng`; v1 miss r3 **recovered** |
| slow_db | 8/11 | **9/11** | db_latency via `toxiproxy`/`mysqld`; v1 burst misses **recovered**; 2 subtle-60 ms missed |
| svc_net | 5/5 | **4/5** | service_network on `java` (carts); r1 hedged "other" this sample |
| svc_mem_cap | ⛔ n/a | **3/8 DET + 2 PARTIAL** | re-collected w/ memcg 29-30 Oct, eval 31 Oct (§svc_mem_cap below); memcg reclaim on carts (pid_ns 4026532540); subtle 2/3 > aggressive 1/5 |

**Sock Shop headline (v2, fixed blueprints): 27/31 scored = 87 % DETECTED** on the four evaluable
blueprints (noisy r2 lost to a rate-limit, resumable), each with correct localisation and a
window overlapping the injection, on faults the dataset's own verification confirms bit.
Conservative grading throughout ("other"/"normal"/"unknown" = MISS).

> ⚠️ **PRELIMINARY — single run per cell, not the final number.** The agent (gpt-6-luna) is
> nondeterministic, so a borderline cell can flip DETECTED↔"other" between samples on noise alone:
> the three targeted v1 misses recovered cleanly (correct mechanism), while two *other* cells that
> detected in v1 (cpu subtle_r2, svc_net r1) hedged to "other" in this single v2 sample — both
> still localised the right victim. The **final numbers come from the N-seed run after the
> blueprints are frozen**; these guide fixing, they are not citable as the result yet.

### svc_mem_cap — re-collected with memcg tracepoints, now evaluable (Sock Shop)

**The gap (v2), now fixed.** The original Sock Shop/Train Ticket v2 profile recorded **zero memory
events** (no `mm_vmscan_*`, `memcg_reclaim`, `oom`, `kswapd`) — a `collect_trace.sh` bug (the
`vmscan_*` wildcard matched nothing; the real tracepoints are `mm_vmscan_*`). So svc_mem_cap was not
evaluable on microservice, while agentic svc_mem_cap (whose profile DID carry the memcg tracepoints)
reached 44/44. **Sock Shop svc_mem_cap + anomaly_mem were re-collected 29-30 Oct 2026 with the memcg
tracepoints** (5 aggressive + 3 subtle each, 8/8 verification-confirmed); r2's injection window
alone holds 1,238 `mm_vmscan_memcg_reclaim` begin/end pairs vs 0 before. **Train Ticket still has
the gap** (not re-collected) — svc_mem_cap stays not-evaluable on TT.

**Result (Sock Shop, 31 Oct, by hand — `results/sockshop/JUDGMENTS-svc_mem_cap.md`):** 8 runs,
matched arm, blueprint `4_svc_mem_cap`, direct OpenAI gpt-6-luna.

| grade | count | runs |
|---|---|---|
| **DETECTED** | **3/8** | aggr_r3, subtle_r1, subtle_r2 |
| PARTIAL | 2/8 | aggr_r1 (committed memory_limit + carts but self-hedged "unconfirmed"); aggr_r5 (mechanism right, PID→ns unmapped) |
| MISS | 3/8 | aggr_r2, aggr_r4, subtle_r3 (all committed `other`) |

By intensity: **subtle 2/3 DETECTED > aggressive 1/5** clean. Localization verified by **mechanism,
not nsmap** (whose CPU correlation mislabelled carts here as front-end): the in-window memcg reclaim
is `java` in pid_ns 4026532540 = carts (299 events r1, 236 subtle_r2), so the agent's named pid_ns
is the correct victim.

**Honest reading** — not a regression vs agentic 44/44, a harder setting:
- The signal is present in all 8 and the agent *found* the reclaim in carts in every run, including
  the misses. The fix works at the eval level.
- Detection is lower than agentic because (a) a 13-container app also demands *localization*
  (pid_ns→service), which failed twice, and (b) the aggressive 160m cap causes a violent teardown
  the agent twice read as "workload teardown" → `other`.
- Subtle (300m) reads cleaner than aggressive (160m): the gentler cap gives sustained reclaim
  without the dramatic collapse. A real, reportable pattern.
- Failures are over-conservatism, never hallucination: the agent never asserted a cap that was not
  there; where it missed, it declined to commit. Safe failure direction.

> ⚠️ **Single run per cell = preliminary** (same caveat as the rest of §3). Also the **first run on
> the direct-OpenAI provider** (§1-3 used OpenRouter); this model needs `reasoning_effort=none` via
> chat.completions, so reasoning is off — as the OpenRouter chat path effectively was too. The
> N-seed run after the freeze gives the citable number.

Cost: **$0.97** for the 8 cells (9.3 M in + 75 k out tokens, ~13 min wall at jobs=6).

### Train Ticket — a poor testbed (dataset, not the agent); hand-pass complete

> ⚠️ **These TT numbers are from the v1 (pre-fix) blueprints — Train Ticket has NOT been re-run
> on the fixed (v2) blueprints.** The v2 re-run so far covers Sock Shop only. TT should be
> re-run on v2 before any TT detection number is used. The dataset conclusions below (caps that
> did not bite, unreliable verification labels, the memcg gap) are properties of the *data* and
> are unaffected by the blueprint version, so they still hold; only the per-run detection grades
> would change with v2.

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

## Pending sections / next steps

- [x] Sock Shop × 4 evaluable blueprints — v2 (fixed blueprints), **single-run preliminary** 27/31 (§3)
- [x] **svc_mem_cap × Sock Shop** — re-collected w/ memcg (29-30 Oct), eval 31 Oct, single-run
  preliminary **3/8 DET + 2 PARTIAL** (§svc_mem_cap). Now 5 evaluable Sock Shop blueprints.
- [x] re-collect **Sock Shop** with memory tracepoints → svc_mem_cap evaluable (DONE 29-30 Oct)
- [ ] re-collect **Train Ticket** with memory tracepoints → svc_mem_cap still not-evaluable on TT
- [ ] **Freeze the blueprints, then the N-seed run** (several seeds per cell, now incl. svc_mem_cap)
  → the final, citable Sock Shop numbers that do not move afterward. Replaces every single-run number.
- [ ] **Train Ticket on the v2 (fixed) blueprints** — only v1 has been run on TT so far.
- [ ] microservice `normal`-run controls (false-alarm rate per blueprint)
- [ ] svc_cpu_cap + svc_mem_cap × agentic (Codex) — traces on Zenodo
- [ ] control arm (`--arm none`, no blueprint) for the blueprint-value comparison

### Note: does the host-scope scorer fix change the agentic numbers? No.

Re-scoring all 86 agentic cells with the post-fix scorer changed **0** of them (svc_cpu_cap
42/42 and svc_mem_cap 44/44 identical). The fix only fires when `truth["scope"] == "host"`;
agentic caps are `scope == "cgroup"`, so that branch never runs for them. §1–2 stand as-is.
