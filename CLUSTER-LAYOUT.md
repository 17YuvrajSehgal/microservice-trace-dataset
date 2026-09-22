# Where things live on Trillium

Everything for this project sits under **`/scratch/yuvraj17/stratatrace/`**.
Before 2026-09-03 it was spread across the scratch root, mixed with four other projects.

```
/scratch/yuvraj17/stratatrace/
├── dataset/       **THE v2 DATASET. Everything about it is in here.**
│   ├── README.md      generated - counts, per-family tables, what one run holds, the traps
│   ├── INVENTORY.csv  one row per run, generated from the runs themselves
│   ├── runs/          the extracted runs, what analysis reads      7.7 TB, 304 runs
│   │   ├── sockshop/<family>/<run_id>/ + <run_id>_metrics/ + <run_id>_load.csv
│   │   └── trainticket/...
│   ├── archives/      the same runs as .tar.gz, one per family     844 GB
│   │   ├── sockshop/      29 archives
│   │   ├── trainticket/   22 archives
│   │   └── provenance/    Prometheus TSDB, campaign manifests, collection logs, VM images
│   └── index/         per-run kernel event count tables (build_ctf_index.py)
├── attic/         kept, not deleted, not part of the dataset
│   ├── superseded-20260917/     retired runs                        1.3 TB
│   ├── superseded-20260915-issue17/  empty
│   └── v1-and-earlier/          l0, stratatrace-v1, agentic-runs    2.8 TB
├── repo/          the git clone
├── data/          symlinks back to the above, plus packs/ and ctfcache/
├── results/       one dir per experiment (q2, q2b, withwithout, blockio, ...)
├── tools/         bt21.sh, local-bt21/ (babeltrace 2.1.2), src/
├── scripts/       loose helper scripts from past sessions
├── slurm-logs/    job .out / .err / .log files
├── misc/, work/   leftovers
```

Reorganised 21 Sept 2026 by `transfer/organize_dataset.sh`. Before that the dataset was in
three unrelated-looking places - `data/stratatrace-v2`, `v2/` (four subdirectories) and
`data/ctf-index` - with the retired runs and 2.8 TB of v1 material beside them and nothing
saying which was current.

Nothing was deleted. Every move was a rename inside /scratch, and the old paths
(`data/stratatrace-v2`, `data/ctf-index`, `data/l0`, `data/stratatrace-v1`,
`data/agentic-runs`) are symlinks, so anything still pointing at them works.

Run `transfer/make_inventory.py` after adding or retiring runs. It rewrites README.md and
INVENTORY.csv from the runs on disk, so the counts cannot drift.

v2 and v1 must never share a root: v2 reuses every v1 recipe name, so one release's archives
would overwrite the other's with no way to tell them apart. That is why v1 sits in `attic/`
rather than beside the v2 runs.

## Retention

`/scratch` is safe for this data for **at least a year** (confirmed 2026-09-06). No need to chase
`/project` quota for the v2 release - which is just as well, since `/project` has ~705 GB free
against a 1024 GB quota and could not hold v2's 779 GB alongside what is already there.

Space as of the v2 push: **4.8 TB of 25 TB**, and **~1.0M files of 10M**. The per-recipe tarball
design is why the file count barely moved - v2 is 831,416 source files stored as **51 archives**.

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
