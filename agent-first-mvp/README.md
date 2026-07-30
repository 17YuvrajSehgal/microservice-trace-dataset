# Agent-First, Collection-Aware Observability — MVP

Agent-first observability where a **skill** compiles a plain-language problem into a
machine-readable *collection spec* — a different one per problem — then runs a
kernel-deep RCA over Babeltrace2 + OTel traces + logs + metrics, and returns a clean
visual verdict. The novel unit is the *collection-aware skill*: no incumbent (Datadog,
Dynatrace) or academic system (TMLL, TAAF, HolmesGPT) decides *what to collect from the
problem statement*, and none go kernel-deep.

Full plan/architecture: `../DOCS/agent-first-mvp-plan.md`.

## Skill catalog (each maps to a real, calibrated, ground-truth fault in the StrataTrace dataset)

| Skill | Fault | Decisive modality | What it proves |
|---|---|---|---|
| `db-slowness-rca` | slow_db | kernel + traces | socket-wait attribution; rules out disk/CPU |
| `cpu-saturation-rca` | anomaly_cpu | kernel + metrics | names the aggressor process metrics only see as "host busy" |
| `noisy-neighbor-rca` | noisy_neighbor | **kernel-only** | contention invisible to metrics/traces — proves kernel necessity |
| `dependency-outage-rca` | dependency_outage | **traces** + kernel | localizes the dead downstream edge; frozen-cgroup confirm |
| `error-storm-rca` | error_storm | **logs** + traces | driver-error log signatures behind the 5xx spike |

Five problems → five different collection specs → five different decisive modalities:
the system genuinely decides *what to collect*, and it differs each time.

## Layout
```
skills/<skill>/{skill.json, SKILL.md}   # collection-aware diagnostic contracts
engine/                                 # phase1/phase2, bt_graph, ctf_reader, modalities, rca_llm, sizes, benchmark
mcp_server.py  .mcp.json                # FastMCP: discover_skills / phase1_requirements / run_skill / query_result
live_capture.py                         # MODE A: scoped LTTng capture (reuses collect_trace.sh + fault recipes)
dashboard/                              # self-contained HTML verdict/catalog/benchmark
demo_cli.py                             # deterministic all-acts fallback (no MCP/agent)
```

## Dataset safety
The MVP is **read-only** on `~/traces` (the 164 GB StrataTrace dataset). All
decompression/outputs go to `~/mvp_work/`; live captures to `~/mvp_captures/`. A
full-disk snapshot (`stratatrace-dataset-safe-20260729`) backs up the dataset.
