# Decisions — 15-08-2026

## v4 skill layer BUILT (registry + evidence-driven selector + 12 skills) — branch `new-agentic-architecture`
Implemented new_design.md §5 in one pass (commit 5470e58), offline-tested (both SDK families) and
API-smoke-verified on the cluster:

- `skillreg.py` — markdown skill registry (simple frontmatter + `## Problem signature` /
  `## Investigation blueprint` / `## Resolution template`; NO YAML dependency — cluster venv has no
  pyyaml). `covers: <family>` is harness metadata (LOFO + selection scoring), never shown to the
  model. **Lint**: evaluation-grade skills are service-agnostic — benchmark identifiers (SS/TT
  service names, injection containers, gt vocab, `aggressor`, `stress-ng`) are forbidden in bodies;
  `load_skills(strict=True)` refuses a dirty library.
- Selector: ONE structured LLM call (select_skill tool, dict/str args both parsed), input = the
  **masked Phase-1 evidence survey only** (evaluation mode: nothing states the problem), explicit
  ABSTAIN ("a wrong skill misleads and is worse than none").
- `context_builder.py` — deterministic survey digest (topology top edges / trace p95 top / log
  changes / metric movers + host / kernel changes) — the Context Builder seed. NOT injected into
  the diagnosis agent yet (kept out so the skill effect is the only variable vs v3; brief-injection
  is a separate future toggle).
- `agent.py` — `skills=` param: survey → mask → select (retry-wrapped) → skill body appended to the
  system prompt with "abandon it if evidence contradicts it"; abstain = plain frozen-v3 path. New
  transcript events: `survey`, `skill_selection` (evidence + skills shown + tokens),
  `skill_injected`. Selector tokens/survey bytes counted into the row costs.
- `evaluate.py --skills off|full|lofo` (+`--skills-dir`); LOFO removes the incident's own family
  per incident; `selection_correct` scored harness-side (full: covers==family; lofo: abstained).
- `audit_leakage.py` — new channels: survey/selector evidence = full per-incident scan; skill
  library text + injected bodies + system prompt = static scan + service-name lint (imports
  skillreg's forbidden pattern). This caught the base v3 prompt's phrase "no visible aggressor" →
  reworded to "no visible culprit workload" (one-word prompt change; S0 is re-measured within the
  v4 campaign anyway; master's frozen v3 untouched).
- `skills/` — **12 evaluation-grade skills**, one per injected family, written against the real
  tool vocabulary (host_disk_io_time_s/s, off_cpu_io_wait, cpu_throttled_s/s, change_x, …), each
  with discriminating look-alike rules (db_latency vs dependency_outage vs error_storm;
  cpu_saturation vs noisy_neighbor vs cpu_throttling; host vs single-service scope). All lint-clean.

## Smoke results (4 incidents, real API) — the design behaves as intended, both ways
- **S1 SS anomaly_disk: right skill @0.98 → aggressor/disk_io fully correct in 11 calls.**
- **S2 (LOFO) SS anomaly_disk: correct ABSTAIN @0.91 with 11 distractors → first-principles
  fallback still fully correct** — the never-seen-fault path demonstrated end-to-end.
- TT slow_db false-matches `service-network-path-rca` in BOTH modes (0.81/0.77) and the wrong
  skill steers the agent to a victim — this incident's evidence is genuinely path-shaped (~30s
  timeout plateaus). Exactly the false-match/distractor phenomenon §6 is designed to measure; the
  agent did NOT exercise its "abandon the skill" permission (worth analyzing in the campaign).
- Auditor PASS 4/4 including the new skill channels.

## Campaign STOPPED early (Yuvraj: small test only for now; big runs later)
Killed the S1+S2 driver after 4 S1 incidents. **Small-test verdict over 8 real incidents: the
skill layer works end-to-end.**
- S1 with correct selection (4/4 host faults incl. the 3 partials): right skill chosen
  (conf up to 0.98) → aggressor + correct fault type every time, ~11 calls each —
  TT anomaly_cpu/disk/mem all BOTH-correct (v3 got these too, but at 12-16 calls).
- S2 LOFO (SS anomaly_disk): correct ABSTAIN @0.91 among 11 distractors → fallback still fully
  correct — the never-seen-fault path demonstrated.
- Known misses to watch at scale: TT slow_db false-matches service-network-path (both modes; its
  evidence is genuinely path-shaped); TT anomaly_net wrongly abstained (skill present) →
  fallback got host (svc ✓) but fault ✗. Auditor PASS on every transcript incl. skill channels.
Partial results kept at `results/gate_s1/` (4 files) + `results/skills_smoke/`; the driver is
resumable (skip-if-exists), so the full campaign later just re-runs `gate_skills_driver.sh`.
Monitor note: inline `$(…)` through `wsl ssh` breaks — always use a status SCRIPT on the cluster
(second time this bit).

## Shared Investigation Context BUILT (v4 item 2) + injectable investigation brief
`shared_context.py`: per-investigation typed claim store — every Phase-1 finding becomes
`{kind, subject, predicate, value, text, source}` with provenance (kinds: inventory,
topology_edge, latency, log_change, metric_mover, host_signal, kernel_change, wait_attribution).
`context_builder.build_context()` populates it; the selector's digest and the NEW injectable
brief are both views over the same store (Phase 1 runs ONCE). Masking discipline: views render
FROM the masked digest (pure function), so no raw name can reach the model through prose; the raw
claim set is recorded as a `shared_context` transcript event for auditors.

`evaluate.py --brief`: brief injection measured as its own condition; **off keeps every existing
condition byte-identical** (v3/S0/S1/S2 unchanged). Cluster smoke (1 incident, SS anomaly_mem,
brief-on skills-off): fully correct (aggressor/memory_pressure, 12 calls), 45 claims, masked
brief verified in the transcript, auditor PASS. Offline suites green on both SDK families.

Next per new_design.md build order: `query_source` tool → related-incidents retrieval (with
auditor rules first) → skills mining loop; campaign runs when Yuvraj green-lights bigger runs.

## v4 FEATURE TEST (20 audited runs) — machinery works; selector calibration + one tool gap are the levers
11 new targeted runs (S1 ×5 on v3-miss/edge families, brief ×4 on hard cases, LOFO ×2) + 9 prior
smokes/partials, all vs the S0=v3 baseline. Full report: `agentic-rca/RESULTS-v4-featuretest.md`.
Highlights: TT svc_cpu_cap S0✗→S1 both✓ (the skill fixed the fault type); agent OVERRODE a wrong
skill and still scored both✓ (TT dep_outage LOFO); brief harmless + one svc fix; query_source used
organically 2/20. Problems: selector S1 precision 6/11, LOFO abstain 1/4 (adjacent-class confusion —
the discriminators live in Resolution templates the selector never sees; absence-shaped signatures
wrongly abstain); **topology cannot see span-less datastores** (edges need child spans → mysql/*-db
never appear as callees → slow_db structurally looks like service_network — root cause of that
persistent miss; fix = client-span→peer edges from server.address/network.peer.address);
SS queue_backlog regressed to "normal" under S1. Improvement plan A–F in the results doc
(topology peer-edges → selector v2 with discriminators → skill-verification preamble → brief
"survey done" line → skills↔query_source links → queue evidence later). Decision: apply A–D as one
batch, re-test the same 11-incident set once, THEN bigger runs.
`source_tool.py` → agent tool `query_source`, one tool with three ops mirroring the Claude Code
trio: **find_files** (glob, `**/*Order*.java` or basename patterns), **search** (regex/plain text
→ file:line matches, 40-cap with refine note, optional path-glob filter, invalid regex falls back
to literal), **read** (numbered `cat -n` window, start_line/limit≤400, continuation note,
traversal-guarded). Pruned cached walk (.git/deps/build/binaries/old-docs), 256KB search cap,
honest bytes_touched (scanned bytes = the cost of index-free search). Per-app root:
trainticket→`train-ticket/`, sockshop→`microservices-demo/`, `RCA_SOURCE_ROOT` override; missing
corpus → clean note, never an error. One-line hint added to SYSTEM step 4.

Cluster: submodules were NOT initialized on Trillium — `git submodule update --init --depth 1`
(TT 29M, SS 572K). Verified real searches on the TT monorepo (RestTemplate imports,
ts-order-service file listing). **Known limitation:** SS's microservices-demo is the deployment
meta-repo — the Tier-1 service source (front-end/catalogue forks) is NOT vendored here, so
query_source on SS returns little; option later: add the fork repos as extra roots. Leakage:
source is static per app + fault-agnostic; masking applies to outputs as usual; auditor PASS on
agent-wiring tests. Offline suite: find/search/read semantics, pruning, caps, traversal guard,
agent dispatch + transcript + auditor.
