# Where things live on Trillium

Everything for this project sits under **`/scratch/yuvraj17/stratatrace/`**.
Before 2026-09-03 it was spread across the scratch root, mixed with four other projects.

```
/scratch/yuvraj17/stratatrace/
├── repo/          the git clone (was /scratch/yuvraj17/microservice-trace-dataset)
├── data/
│   ├── l0/            raw kernel traces, the big one (~1.3 TB expanded)
│   ├── agentic-runs/  extracted per-run telemetry
│   ├── packs/         allpacks, evidence_packs, evidence_packs_tt, specificity
│   ├── ctfcache/      shared decode cache (see ctf_extract.py)
│   └── stratatrace-v1/  the v1 dataset release
├── results/       one dir per experiment: withwithout, blockio, cpucluster, dbfix,
│                  endpoints, flows, netloss, nettest, retest, comparison,
│                  comparison_tt, verify, repro, peers, reorg, ww-smoke
├── tools/         bt21.sh, local-bt21/ (babeltrace 2.1.2), src/ (its source)
├── scripts/       loose helper scripts from past sessions
├── slurm-logs/    job .out / .err / .log files
└── misc/          leftover odds and ends
```

## Not ours — do not move or delete

Other projects share this scratch space:

`logs`, `final_logs`, `window_shards`, `improved_window_shards`, `enriched_parquet`,
`local`, `JiraAndLogs_scratch`, `RL-StockPrediction-PPO`, `SyntheticLogGeneration`,
`SyntheticLogGeneration_runs`, `stock_trading_logs`, `bakkuScratch`, `neo4j-v3`,
`apptainer`, `ondemand`, `hf_cache`

Two more stay at the root on purpose:

| Path | Why it did not move |
|---|---|
| `adaptive_tracing_scratch/` | older project, and a benchmark still reads traces from it |
| `release/` | June 2026 dataset release, older work |
| `.venv-rca/` | a Python venv bakes in absolute paths and breaks if moved |

## Two traps worth remembering

**1. `allpacks` is 86 symlinks**, not files. They point into `specificity/packs/` and
`evidence_packs*/`. Move those targets and every link dangles. The reorg script relinked
them; any future move must too.

**2. `tools/bt21.sh` lives only on the cluster, not in git.** So when paths changed, its
contents did not follow, and it silently fell back to the system **babeltrace 2.0.4** —
which cannot read our CTF 2 traces at all. The copy in git is
`blueprints/lib/cluster-bt21.sh`; copy it over the live one after any move, then check:

```bash
/scratch/yuvraj17/stratatrace/tools/bt21.sh --version   # must say 2.1.2 "Brossard"
```

## Reading a trace

`kernel/kernel/` in each L0 run holds **gzipped** streams that babeltrace cannot read.
Use `ctf/`, the expanded copy (~14 GB per run, not the 2.2 GB the compressed dir reports).

```bash
TZ=UTC tools/bt21.sh data/l0/sockshop/<run>/ctf --begin HH:MM:SS --end HH:MM:SS
```

`TZ=UTC` is required. babeltrace prints *and reads* `--begin/--end` in the local zone, and
these traces were written in UTC. Without it the window silently matches nothing.
