# Decisions — 13-08-2026

## Masked sanity gate re-run (leakage-controlled) — 74/74/61 RETIRED, honest gate = 48/17/9
Re-ran the 23-incident P2 gate on Trillium (login node, per-family chunked driver
`agentic-rca/gate_masked_driver.sh`, resumable, ~70 min/pass) with `RCA_MASK_NAMES=1`, full
transcripts, and the leakage auditor. Two passes were needed:

- **v1 (raw-name aliases): 26% / 17% / 4%.** Diagnosed a masking artifact: kernel L1 names the
  injected workload `aggressor` while metrics says `anomaly-cpu-stress` → raw-name hashing gave ONE
  entity DIFFERENT pseudonyms across tools, destroying cross-tool identity the unmasked names
  carried. Fix: `leakguard._canon` — the injected-workload vocab class shares one alias per run
  (toxiproxy = its own class). Identity is legitimate information; name semantics are not.
  v1 preserved at `results/gate_masked_v1_fragmented_aliases/` as the design datapoint.
- **v2 (canonical aliases) — number of record: service 48% / fault 17% / both 9%** (avg 19.1 tool
  calls, ~500k in-tokens for all 23). `RESULTS-agent-sanitygate-masked.md` has the full table;
  old RESULTS-agent-sanitygate.md carries a RETIRED banner.

**What the leak was worth:** ~26 points of service accuracy and ~57 of fault accuracy — the run id
alone was handing the agent the fault type. **What survived:** TT slow_db → mysql localized purely
from kernel L2 wait-attribution ("100% off-CPU I/O wait, no saturation", conf 0.76), and the
pseudonymized aggressor found on 5/9 host faults from resource dominance (e.g. a nameless container
appearing at 6.5 cores). **What it means vs baselines:** masked agent 48% ≈ statistical/mmbaro ~48%,
but the statistical baseline still keys off stress-container NAMES (unmasked) → honest framing is
"parity against a baseline that keeps the naming crutch", and the masking ablation itself is a
paper-worthy caution for injected-fault benchmarks.

Also fixed along the way (all pushed, cluster on `master` now):
- Azure gpt-5.4 intermittently 400s with `invalid_prompt` on telemetry-heavy turns → agent retries
  transient failures (429/5xx/timeout/invalid_prompt) with backoff, retries logged in transcripts.
- metrics field `"injection"` → `"incident"` (leakguard was masking the JSON KEY; also neutral vocab).
  baseline_stat updated for the rename.
- bundle_artifact secret scan restricted to credential-like keys (STRATATRACE_APP=trainticket
  false-positived — benign config values legitimately appear in transcript meta).

**Verification shipped with the results:** `audit_leakage.py` PASS (0 hard / 0 soft) over all 23 v2
transcripts (and v1's). Artifact bundle (23 results + 23 transcripts + schema + sha256 manifest):
`results/artifact_gate_masked_v2.tar.gz`, durable copy at
`/project/def-naser2/yuvraj17/microservice-trace-dataset/artifacts/artifact_gate_masked_v2_20260813.tar.gz`.

## Decision: agent refinement order before the degradation sweep
The v2 misses cluster into two fixable, non-leaking causes: (1) fault-taxonomy confusion (agent
echoes L2 hint vocabulary → "dependency_outage" for slow_db; needs fault-type DEFINITIONS in the
static system prompt), (2) distraction by chronic noise (SS carts' standing 59k-error Mongo storm;
logs/kernel tools are whole-run, not window-filtered — a pre-existing tools.py issue that now costs
accuracy). Plan: apply (1)+(2), ONE re-gate, then freeze the agent for the sweep. Do NOT iterate
per-incident on prompts (overfitting the gate).

## Agent ROBUSTNESS overhaul (Yuvraj: "results not acceptable; agent must find faults without hints")
Executed the refinement plan as ONE batch of generic, fault-agnostic upgrades, then ONE re-gate:
- **tools.py**: (a) baseline→incident discipline in EVERY tool — logs now report error-rate change
  + NEW signatures (chronic noise flagged; the 190-err/min storm reads ×1.1 = background), kernel
  L1 compared across windows (was whole-run peaks); (b) **query_topology** — caller→callee edges
  from span parent/child with baseline-vs-incident p95 (victims' slow edges point AT the culprit);
  (c) **host channel** — node-exporter curated signals as service `host` + host-kernel L1 row
  (host faults = 9/23 incidents, previously no direct evidence channel); (d) container-name
  normalization — SS per-service metrics queries were SILENTLY EMPTY (`carts` vs
  `docker-compose_carts_1`); (e) per-series counter rates (mixing device/cpu label series in one
  max-min made garbage; pandas groupby-dropna zeroed all host counters — both fixed).
- **agent.py SYSTEM**: 5-step method (survey CHANGES → blast-radius shape → walk topology
  downstream → kernel mechanism → submit) + operational definitions of the 13 fault labels
  (answer-space, static, identical every incident — not a hint).

**Gate v3 (leak-free): service 83% / fault 48% / both 48%** — vs v2 48/17/9 and the RETIRED leaky
74/74/61 — at LOWER cost (13.5 calls, ~9.2k out-tokens total). All six host anomaly_{cpu,disk,mem}
fully correct on both apps (aggressor + fault type); SS slow_db fully correct; dependency_outage
fully correct on both apps. Auditor PASS 23/23 (0 hard, 0 soft). Leak-free agent now clearly beats
both baselines (stat 38% both, mmbaro 46% AC@1). Bundle:
`/project/…/artifacts/artifact_gate_v3_robust_20260813.tar.gz`. Updated
`RESULTS-agent-sanitygate-masked.md` §0.

Remaining misses (documented, NOT iterated on — anti-overfitting): SS anomaly_net, SS
queue_backlog, SS svc_mem_cap, TT slow_db (victim-named this run; v2 got it — borderline), fault
labels at taxonomy boundaries (noisy_neighbor↔cpu_saturation; error_storm described accurately as
connection-resets but labeled dependency_outage). **Decision: FREEZE the agent here for the
degradation sweep** — v3 is the fixed method; further prompt/tool iteration against the gate would
overfit the 23 dev incidents.
