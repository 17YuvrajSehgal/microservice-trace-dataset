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
