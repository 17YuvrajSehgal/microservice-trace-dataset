# ICSE Industry Challenge — preparation plan

Target: **ICSE industry / SE-in-Practice track.** Working premise: the current paper and
architecture are **not yet at ICSE level** — not because the ideas are weak, but because the
**rigor around them** (baselines, statistics, a working selector, a second real app) is missing.
This plan fixes that, ordered by reviewer impact.

> One open input gates the schedule: **the deadline / runway**. The plan is phased so it adapts —
> P1 is non-negotiable, P5 is polish. Dates go in once the deadline is set.

---

## 1. The story (contribution framing)

**Hero = the method.** *Blueprint-guided, kernel-trace root-cause analysis for microservices: an
LLM agent that reads kernel traces through per-fault "blueprints" (structured domain knowledge +
tools), and what it takes to make it reliable.*

**Artifact underneath = the dataset.** StrataTrace v2 — a 4-modality (metrics, logs, distributed
traces, **kernel traces**), kernel-level, labeled-fault corpus across two real microservice apps.
This is what makes the modality-ablation claim possible and is a contribution in its own right.

**Why it's novel / industry-relevant.** Most RCA/AIOps works on metrics, logs, or app traces;
**kernel-level RCA is underexplored**, and it sees faults the upper layers miss (a CPU cap, packet
loss, memcg reclaim). The blueprint abstraction is the practical bridge: raw LLMs flail on 2M-event
kernel traces; structured playbooks + tools make it tractable. The honest operational lessons
(faults that don't bite, wrong verification targets, collection gaps) are exactly what the industry
track rewards.

**Three claims the paper must support with evidence:**
- **C1 (value of blueprints):** blueprint-guided >> raw-LLM-on-trace. *(ablation: blueprint on/off)*
- **C2 (value of kernel traces):** kernel modality adds faults the others miss. *(modality ablation)*
- **C3 (autonomy):** the agent can *select* the right blueprint itself, not just execute a given one.
  *(the selection experiment — currently the weakest link)*

---

## 2. Honest state — reviewer lens

| area | where we are | reviewer verdict today |
|---|---|---|
| Dataset | 304 runs, 2 apps, 4 modalities, kernel-level, labeled; on Trillium | strong, but has documented holes (below) |
| Matched-arm detection | Sock Shop ~87% (cpu 7/8, noisy 7/7, slow_db 9/11, net 5/5); agentic cpu 14/31 severity-graded, mem 44/44 bite-aligned | promising but **single model, single run, no baseline** |
| Blueprint selection | naive 28% → drill-to-root 47% → Router C iterating | **not yet credible; the autonomy claim (C3) rests on this** |
| Baselines | none | **desk-reject risk** |
| Statistics | point estimates from a nondeterministic LLM | **desk-reject risk** |
| Generalization | effectively Sock Shop only (Train Ticket faults didn't bite) | reviewers want ≥2 working apps |
| Scoring integrity | by-hand JUDGING rubric + bite-aligned ground truth; leakage audited | a genuine strength — keep it |

**Dataset holes to fix or document airtight:**
- `svc_mem_cap` not evaluable on microservice — the v2 kernel profile omitted `mm_vmscan`/memcg/oom
  tracepoints. Re-collect with them enabled, or exclude + document.
- Train Ticket: caps didn't bite (`ts-travel-service` ~0.005 cores vs a 0.2-core cap); several
  verification labels were wrong (`no_metric_signature`). Re-collect with stronger, verified faults.

---

## 3. Reviewer-kill risks → the must-haves

1. **No baselines → desk reject.** Must add: raw-LLM-no-blueprint, modality ablation, one non-LLM
   RCA reference.
2. **No statistics → desk reject.** Must add: N seeds + mean ± CI, ≥2 models.
3. **Selection unsolved → the autonomy claim collapses.** Must land a credible selection number, or
   reframe honestly as operator-assisted with selection as the studied open problem.
4. **One app → weak generalization.** Must get a second real app working, or defend single-app with
   a strong lessons narrative.

---

## 4. Work plan, ordered by reviewer impact

### P1 — the experiments that decide accept/reject (do first)
- **P1.1 Baselines.**
  - *Raw-LLM-no-blueprint* (`--arm none`, already supported): same agent, raw trace+index, no
    blueprint → isolates C1.
  - *Modality ablation* on the dataset: metrics-only / logs-only / traces-only / kernel-only / all
    → isolates C2. (This is the dataset's headline selling point.)
  - *Non-LLM reference*: at minimum a metric-threshold / statistical anomaly detector over the
    per-run Prometheus export; a published trace-RCA method if one ports cheaply.
- **P1.2 Statistical rigor.** N≥3 seeds per cell (per-cell `result.json` already resumable); report
  mean ± 95% CI (bootstrap). Add a **second model** (≥2 total) — budget permitting a third.
- **P1.3 Finish the selector (C3).** Continue the evidence-driven Router-C loop to a credible
  number (target >80% Sock Shop), then freeze and run seeded. If it stalls, reframe honestly.

### P2 — generalization
- **P2.1 Re-collect Train Ticket** with faults that bite (verified on the request path) + memcg
  tracepoints enabled; re-run matched-arm + selection → two working apps.
- **P2.2** (fallback) if time-limited: Sock Shop only + a rigorous "why TT failed" lessons section.

### P3 — the dataset contribution
- **P3.1** Fix or document the `svc_mem_cap` tracepoint gap (re-collect with the memory profile).
- **P3.2** Package the artifact: dataset + harness (`Blueprint/eval`, blueprints, `agent_v2`),
  reproduction scripts, a datasheet. Aim for an ICSE artifact-evaluation badge.

### P4 — the writing
- **P4.1** Rebuild the paper around C1–C3 with the baselines/CIs. Sections: problem & industry
  motivation → dataset → method (blueprints + selector) → evaluation (ablations, baselines, CIs) →
  lessons learned → threats → related work (AIOps, trace-RCA, LLM-for-ops).
- **P4.2** Figures: the selection decision tree (have it), the architecture, the ablation/CI plots.

### P5 — polish
- Cost/latency per diagnosis (industry cares), prompt-caching to cut cost, extra fault families
  (fd_exhaustion, conn_pool, lock_contention, …) if the core is solid.

---

## 5. Evaluation protocol (the rigor spec — lock before the big run)

- **Conditions:** {blueprint-given, blueprint-selected, no-blueprint} × {kernel, metrics, logs,
  traces, all} × {model A, model B} × N seeds.
- **Metrics:** detection (fault type), localization (victim service / WHERE), window IoU, selection
  accuracy (confusion matrix) + **end-to-end unassisted** (select→detect, the real-world number),
  and **cost + latency per diagnosis**.
- **Ground truth:** the recipe + the cgroup/kernel counters (bite-aligned), never the metric labels
  alone (TT showed those can be wrong). Scoring by the `JUDGING.md` rubric, not keyword matching.
- **Reporting:** mean ± 95% CI everywhere; no single-run numbers in the paper.
- **Fairness:** blueprints stay leakage-audited (no dataset answers in the prose); pre-register the
  predictions; the agent never sees ground truth.

---

## 6. Assets we already have (reuse, don't rebuild)

- **Agent:** `Blueprint/agent/agent_v2.py` (LangGraph plan→workers→review→synth; blueprint worker).
- **Blueprints (5):** `Blueprint/latency/{1..5}` — cpu_cap, noisy_neighbor, slow_db, svc_mem_cap,
  svc_net; CRLF/`$BT2`/baseline fixes applied; leakage-audited.
- **Selector:** `Blueprint/select*/` — naive, drill-to-root (A), panel (B), robust (C) + fixes.
- **Eval harness:** `Blueprint/eval/` — `eval_matrix.py`, `eval_one.py`, `score.py`, `JUDGING.md`
  (by-hand rubric), `select_score.py`, `build_indexes.py`, `RESULTS.md`.
- **Data:** StrataTrace v2 on Trillium (`/scratch/yuvraj17/stratatrace/`); index-v2 (142 built);
  agentic runs local + indexed.
- **Prior honest results** (preliminary, to be re-run seeded): `Blueprint/eval/results/`.

---

## 7. Threats to validity (state them up front — they're strengths here)

- One trace-collection environment; LLM nondeterminism (mitigated by seeds + CIs).
- "Fault set ≠ fault bites" — detection conditioned on faults that measurably bit; abstention
  measured on non-biting + control runs.
- Blueprint-authoring is human effort; argue it's a one-time, transferable cost and ablate its value.
- Generalization bounded by the apps evaluated; TT limitations documented.

---

## 8. Open decisions (need from Yuvraj)

1. **Deadline / runway** → turns the phases into dates.
2. **Existing draft?** (the MSR-oriented `msr-research.md`) — adapt or start fresh for ICSE.
3. **Model budget** for the ≥2-model, N-seed campaign (OpenRouter spend) → sets how big P1.2 goes.
4. **Second-app call:** re-collect Train Ticket (P2.1) vs Sock-Shop-only + lessons (P2.2).

*Draft plan — not committed. Update as decisions land.*
