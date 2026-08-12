# Results — LLM+kernel agent sanity gate (RCA method #3)

**P2 sanity gate PASSED.** The tool-using LLM agent (Azure **gpt-5.4**, via the OpenAI-compatible
config) diagnoses incidents at 100% telemetry — the go/no-go before any degradation sweep. Run:
`python agentic-rca/evaluate.py --app … --method agent --grid full`.

## Headline: the agent beats both non-LLM baselines
Per-family sample (one incident per fault family), Top-1 **service localization** (comparable across
all methods) and **both-hit** (service AND fault, agent/statistical only):

| method | Top-1 service | both-hit | recovers slow_db? |
|---|---|---|---|
| statistical (#1) | ~55% | 38–45% | ❌ 0% |
| RCAEval mmbaro (#2) | 44–48% | — (localizer only) | service-only (50%) |
| **LLM+kernel agent (#3)** | **73%** | **~60%** | ✅ **both (mysql / db_latency)** |

Train Ticket (11 incidents, complete): service 73% · fault 73% · both 55%. Sock Shop (in progress):
aggressor/resource faults correct (cpu/disk/mem). Combined so far: **73 / 73 / 60%**.

## Why it wins — it *reasons* over the kernel (the thesis, live)
On `slow_db` the agent's own evidence:
> "…user-facing victims all show **off-CPU external wait** rather than CPU/memory pressure … **Kernel
> evidence on mysql attributes 100% of wait to off-CPU external I/O/dependency wait** with elevated
> syscall latency, while mysql has no saturation signals — consistent with an induced database-latency
> fault, not an application bug."

That is the **kernel-as-safety-net** claim demonstrated: the agent used the L2 wait-attribution to nail
the exact fault both baselines miss. It also correctly separated victims from the culprit (RQ3), and
identified the injected stress containers on host faults.

Cost/behaviour: ~**19 tool calls/incident** (thorough multi-modal investigation), ~700 out-tokens/incident.
Misses cluster on host-network faults (`anomaly_net`, `svc_net`) and `dependency_outage` (named a
neighbor instead of the dead service) — candidates for prompt/tooling refinement.

## Operational constraint (important for the full sweep)
- The agent needs outbound HTTPS to the LLM endpoint → **login node only**. **Compute nodes have no
  internet** (verified: `curl` to the Azure endpoint times out, no proxy) — so agent runs cannot be
  Slurm batch jobs.
- SciNet **login-node watchdog** kills long cumulative processes (a single incident ≈ 2 min / 7.4 GB
  is fine; 23 back-to-back got killed mid-run). **Run the agent in short per-family chunks** (each a
  fresh process) — see the SS gate driver.
- Implication for the **full agent degradation sweep** (93 × 15 = 1,395 agent runs): login-node
  chunked, and a **real Azure-credit budget** (~1,400 multi-tool-call diagnoses). Scope/subsample
  deliberately (e.g. the trace/kernel axes on the blind-spot families first).
