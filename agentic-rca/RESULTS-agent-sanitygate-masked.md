# Masked sanity gate — the honest agent numbers (2026-08-13)

**TL;DR: the 2026-08-11 gate numbers (74% / 74% / 61%) were inflated by label leakage
and are retired.** With leakage closed, the honest gate is **service 48% / fault 17% /
both 9%** (23 incidents, Azure gpt-5.4, 100% telemetry). Service localization is now at
parity with the non-LLM baselines instead of above them; fault-type classification —
which the run id used to hand the agent for free — collapsed and is the main
improvement target. The kernel thesis survives: the masked agent still localizes
`slow_db`→mysql and finds the hidden aggressor on host faults, purely from evidence.

Everything here is fully auditable: every diagnosis has a full transcript
(TRANSCRIPTS.md schema) and `audit_leakage.py` passes over all 23 with **0 hard leaks,
0 soft warnings**.

## 1. What leaked before (audit of 2026-08-13)

| Channel | Leak | Status |
|---|---|---|
| User prompt | run id `tt_slow_db_aggressive_steady_r1` spells fault/intensity/workload | **fixed** — model gets `incident-<sha256[:8]>` |
| Telemetry identifiers | `anomaly-{cpu,mem,disk}-stress`, `noisy-neighbor` containers; kernel L1 service `aggressor`; `toxiproxy` | **fixed** — leakguard pseudonymizes (`container-<hash>`) |
| Tool field name | metrics column was literally `"injection"` | **fixed** — renamed `"incident"` |
| L2 rows | carry `fault_name`/`fault_target` deriver QC columns | never exposed; guard comment added in tools.py |
| Window | exact injection window as "alert time" | kept, documented — standard RCA-benchmark assumption, identical for all methods |
| Process signatures | `stress-ng` in log/kernel evidence | kept, documented — legitimate SRE evidence (reveals a synthetic workload, not which fault) |

Masking is ON by default (`RCA_MASK_NAMES=1`); the unmasked mode exists solely to
quantify the giveaway. The agent answers in alias space and is unmasked before
scoring, so scoring and baselines are untouched.

## 2. Results (same 23 incidents, same model, same tools)

| Gate | service | fault | both | avg tool calls |
|---|---|---|---|---|
| 2026-08-11 unmasked (**retired**) | 74% | 74% | 61% | ~15 |
| masked v1 (raw-name aliases) | 26% | 17% | 4% | 21.8 |
| **masked v2 (canonical aliases) — the number of record** | **48%** | **17%** | **9%** | 19.1 |

v1→v2: raw-name hashing gave the injected workload *different* pseudonyms in
different tools (kernel calls it `aggressor`, metrics `anomaly-cpu-stress`),
destroying cross-tool identity that the unmasked names carried — a masking artifact,
not agent failure. v2 gives the injected-workload class one alias per run
(`leakguard._canon`). That alone doubled service accuracy: identity information is
legitimate; name *semantics* are not.

### Per-incident (v2)

| app | family | target | predicted | fault pred | svc | fault |
|---|---|---|---|---|---|---|
| SS | anomaly_cpu | host | carts-db | db_latency | ✗ | ✗ |
| SS | anomaly_disk | host | carts | error_storm | ✗ | ✗ |
| SS | anomaly_mem | host | **aggressor** | **memory_pressure** | ✓ | ✓ |
| SS | anomaly_net | host | catalogue-db | db_latency | ✗ | ✗ |
| SS | dependency_outage | payment | orders | dependency_outage | ✗ | ✓ |
| SS | error_storm | catalogue | carts-db | db_latency | ✗ | ✗ |
| SS | noisy_neighbor | host | **aggressor** | cpu_throttling | ✓ | ✗ |
| SS | queue_backlog | queue-master | carts | dependency_outage | ✗ | ✗ |
| SS | slow_db | catalogue-db | catalogue | dependency_outage | ✓ | ✗ |
| SS | svc_cpu_cap | carts | carts-db | db_latency | ✓ | ✗ |
| SS | svc_mem_cap | carts | carts | error_storm | ✓ | ✗ |
| SS | svc_net | carts | carts-db | db_latency | ✓ | ✗ |
| TT | anomaly_cpu | host | **aggressor** | noisy_neighbor | ✓ | ✗ |
| TT | anomaly_disk | host | ts-notification-service | dependency_outage | ✗ | ✗ |
| TT | anomaly_mem | host | **aggressor** | **memory_pressure** | ✓ | ✓ |
| TT | anomaly_net | host | mysql | db_latency | ✗ | ✗ |
| TT | dependency_outage | ts-seat-service | nacos | dependency_outage | ✗ | ✓ |
| TT | error_storm | mysql | mysql | dependency_outage | ✓ | ✗ |
| TT | noisy_neighbor | host | **aggressor** | cpu_throttling | ✓ | ✗ |
| TT | **slow_db** | **mysql** | **mysql** | dependency_outage | ✓ | ✗ |
| TT | svc_cpu_cap | ts-travel-service | ts-auth-service | network_latency | ✗ | ✗ |
| TT | svc_mem_cap | ts-order-service | ts-notification-service | dependency_outage | ✗ | ✗ |
| TT | svc_net | ts-basic-service | mysql | db_latency | ✗ | ✗ |

## 3. What survived masking (the thesis holds where it matters)

- **TT `slow_db` → mysql, masked, by kernel reasoning alone** (conf 0.76): *"mysql
  shows no CPU/memory saturation or error storm but kernel wait attribution is 100%
  off-CPU I/O wait with verdict_hint=external_io_or_dependency_wait … the shared
  datastore service is stalled … propagating latency to its callers."* The 08-11
  claim survives at the service level with the crutch removed.
- **The hidden aggressor is findable**: 5/9 host-fault incidents localized the
  pseudonymized injected workload (both `anomaly_mem` fully correct incl. fault
  type; `noisy_neighbor` on both apps; TT `anomaly_cpu`) from resource dominance
  alone — e.g. a nameless container appearing from nothing at 6.5 CPU cores.

## 4. What collapsed (and why it's diagnosable)

- **Fault-type classification (74% → 17%) was mostly the run id.** With names gone
  the agent localizes but mislabels: `slow_db`→"dependency_outage" (it echoes the L2
  hint vocabulary `external_io_or_dependency_wait`), `noisy_neighbor`→"cpu_throttling",
  `svc_mem_cap`→"error_storm". Several are taxonomy-boundary confusions rather than
  wrong mechanisms — fault-definition guidance in the prompt (legitimate, static,
  non-leaking) is the obvious refinement.
- **Distraction by chronic noise**: on SS host faults the agent chased carts'
  standing Mongo error storm (59k whole-run errors) — the logs/kernel tools are not
  window-filtered (known tools.py issue), which now actually costs accuracy. A
  window-filtered logs tool is a legitimate fix, applied equally across conditions.
- **Baseline comparison is now asymmetric in the baselines' favor**: the statistical
  baseline explicitly keys off stress-container *names* (`stress|neighbor|aggressor`)
  and runs unmasked. At masked-agent 48% vs baseline ~48%, the honest statement is
  parity against a baseline that still enjoys the naming crutch — not defeat.

## 5. Artifacts (publishable)

- Transcripts: Trillium `…/agentic-rca/results/gate_masked/transcripts/` (23 files,
  full prompts / raw responses / tool evidence / masked `sent` strings / unmask maps).
- Leakage audit: `python audit_leakage.py --transcripts results/gate_masked/transcripts`
  → **PASS: 23 transcripts audited, 0 hard leaks, 0 soft warnings** (also PASS on v1).
- Bundle: `results/artifact_gate_masked_v2.tar.gz` (23 results + 23 transcripts +
  schema + sha256 manifest; secret-scanned), durable copy at
  `/project/def-naser2/yuvraj17/microservice-trace-dataset/artifacts/artifact_gate_masked_v2_20260813.tar.gz`.
- v1 (fragmented-alias) run preserved at `results/gate_masked_v1_fragmented_aliases/`
  as the masking-design datapoint.

## 6. Consequences

1. Retire 74/74/61 everywhere; RESULTS-agent-sanitygate.md numbers are upper bounds
   obtained with the run-id leak.
2. Before the degradation sweep: (a) fault-taxonomy definitions in the system prompt,
   (b) window-filtered logs/kernel tools, (c) then ONE re-gate. Freeze the agent after
   that; sweep with transcripts + auditor as standard practice.
3. The masking ablation (RCA_MASK_NAMES=0 vs 1) is itself a paper-worthy result:
   naming giveaways were worth ~26 points of service accuracy and ~57 points of
   fault accuracy to an LLM agent — a caution for every injected-fault benchmark.
