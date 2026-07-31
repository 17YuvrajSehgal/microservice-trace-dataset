# StrataTrace — what's left to collect for MSR (and what would help the agent too)

**For:** Naser Ezzati-Jivan · **From:** Yuvraj Sehgal · 30 Jul 2026

We paused mid-collection to build the agentic demo. This is the collection to-do to finish
the MSR dataset (`msr-research.md`), reviewed against what the v1 campaign actually captured,
with a flag on the items that **also strengthen the agentic system** so we collect them once.

**What we have (v1, `progress-notes/28-07-2026/campaign-complete.md`):** 40 runs / 164 GB —
8 fault families (anomaly_cpu, noisy_neighbor, slow_db, error_storm, svc_cpu_cap, svc_mem_cap,
dependency_outage, queue_backlog) + normal, all four modalities time-aligned, ground truth +
verification per run.

**Legend:** 🔴 must (blocks a core RQ / novelty claim) · 🟡 should · 🟢 derive-only, no
re-collection · 🤖 = also unlocks / strengthens the agentic system.

---

## 🔴 Must-collect

### 1. The other three host-resource stressors: **disk, memory, network** (F2/F3/F4) 🤖
We only collected the **host-CPU** stressor (`anomaly_cpu` = F1). The plan's **RQ1 headline
argument** is *"the four host stressors look identical at the app layer (all 'latency up'),
and only the kernel's sched/block/net evidence tells them apart."* **We can't test that with
just CPU.** The recipes already exist (`1_cpu…4_net_stress.sh`) — this is re-collection, not
new work.
- **Agentic bonus:** gives the agent **disk-saturation**, **memory-pressure**, and
  **network-impairment** skills (three of the roadmap chips on the deck).

### 2. The **RQ4 collection-overhead matrix**
The campaign log shows no overhead runs. RQ4 (cost–benefit) is a **non-negotiable core RQ**
and **novelty claim #3** (*"only dataset shipping measured per-modality collection cost"*).
Run the existing fair-overhead protocol (`run_reviewer_overhead_200_fair.sh`) across
conditions **{baseline, +metrics, +logs, +otel, +lttng, all}**, rotated. Without it we lose a
headline figure that no competing dataset can produce.

### 3. **Full Prometheus export** per run (not just the ~33 KPIs) + confirm cAdvisor 🤖
`download_metrics.sh` exports a curated KPI subset. The plan (§M1) requires the **whole label
space** (`query_range` sweep or a TSDB snapshot) so the **metrics modality isn't handicapped**
in RQ1/RQ3 — otherwise "metrics lose to traces" is an artifact of us picking 33 series.
Confirm cAdvisor per-container series actually landed in the bundles (the Docker-29 overlayfs
fix was for exactly this).
- **Agentic bonus:** a skill can request *any* metric it needs, not just the 33 we pre-chose.

---

## 🟡 Should-collect

### 4. **Memory-tracepoint runs** for the memory-layer faults 🤖 *(decision for Naser — see below)*
The curated profile **excludes memory-management tracepoints** (`kmem_/pgfault/reclaim/kswapd`)
— but the plan's own **F3/F8 cards predict a reclaim/pgfault kernel signature**, and **H1**
claims kernel is informative on *every* fault. Today the kernel modality is blind on
memory-layer faults. Recommend: keep the default profile as-is (storage), but collect a
**small memory-augmented set** — host-mem (F3) + svc-mem-cap (F8), 2–3 runs each — with
`kmem_*/vmscan_*/pgfault` added.
- **Agentic bonus:** this is what makes the roadmap **memory-leak** and **gc-pauses** skills
  possible at all — they can't work without these events.

### 5. **Per-container network impairment** (F12 netem) 🤖
Planned but never collected. Gives RQ1 a *service-localized* network fault (vs the host-wide
F4), and the agent a **network-partition** skill (roadmap chip). Apply `tc netem` inside one
container's netns (pumba/`nsenter`).

### 6. **edge-router (nginx) access logs with the `traceparent` header** 🤖
A cheap Tier-3 logs addition (§M3): a topology-wide, request-level record for the **logs
modality** without instrumenting nginx internals.
- **Agentic bonus:** request-level cross-service correlation for the dependency/error skills.

---

## 🟢 Derive / document from what we already have (no re-collection)

7. **Per-service coverage matrix** (spans / logs / per-container metrics / kernel visibility) —
   required by the plan for RQ1/RQ3 fairness; build it from the bundles + `fault_blast_radius.md`.
8. **Confirm Tier-2 trace status** (`user`, `payment`) — instrumented, or label them blind
   spots in the coverage matrix. (dependency_outage localizes via the `orders` caller either
   way, but this must be documented, not left ambiguous.)
9. **Parsed-log JSONL** (`ts, service, container, level, message`) + the **L1/L2/L3 kernel
   representations** — all offline derivations (L2 = the agentic `wait_attribution.py`).
10. **Repair-task ground truth** — confirm every run records its remediation + a recovery-window
    verification (the plan says this "falls out for free" from the cleanup step).

---

## 🤖 Agentic-specific — collect *while* we build (helps both, near-zero cost)

11. **Agent-trajectory capture (M5)** — when the agentic system runs a skill live on the
    testbed, log its trajectory (tool calls, tokens, latency, verdict) in OTel GenAI form.
    Every live run is a *labeled* incident (ground truth already exists) → this builds the
    **paper-2 corpus for free**, and its accuracy is an online replication of the paper-1 study.
12. **Live-capture provenance = dataset-compatible.** Make `live_capture.py` write the same
    clock anchors + metadata snapshots as `collect_trace.sh`, so live captures drop straight
    into the dataset schema.

*(Both are the near-zero-cost §9 hooks: modalities as a first-class list, `fault.layer: agent`
reserved, modality-keyed serializers.)*

---

## Recommendation: one short "wave 2" campaign, then Phase 3

Batch **items 1–6** into a single ~1–2 day collection wave on the VM — same rig, same recipes,
mostly config flips. It **closes RQ1 and RQ4** (the two biggest gaps), and in the same pass
unlocks **four more agentic skills** (disk, memory, network, network-partition). Rough add:
host disk/mem/net ×3 (~9) + memory-augmented mem ×3 (~6) + netem ×3 (~3) + overhead matrix
(~12–18) ≈ **30 runs**, roughly doubling v1 but making the study defensible. After wave 2, move
fully to **Phase 3** (L1–L3 derivers + loader SDK + the ablation study).

## Decisions needed from Naser
1. **Memory tracepoints** — his earlier "exclude memory" vs. the F3/F8 kernel cards and the
   memory-leak/gc skills. Recommend the small memory-augmented subset (item 4).
2. **Full-Prometheus scope** — whole label space vs. an expanded curated set (item 3).
3. **How much wave-2 to run** — full ~30 or the lean must-only (items 1–3 ≈ 20 runs).

*Cross-refs: `msr-research.md` (§M1, §5 catalog, §7 RQ1/RQ4, §9 M5), `fault_catalog.md`
(F1–F12), `fault_blast_radius.md`, `progress-notes/28-07-2026/campaign-complete.md`.*
