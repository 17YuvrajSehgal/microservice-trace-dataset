# Decisions — 08-08-2026

## Agentic-RCA harness runs ON Trillium against the full dataset (no laptop copy)
User has low laptop disk + doesn't want a sample copy. Decision: **run the whole harness on
Trillium**, where the 319 GB of compressed archives already live in `/project/def-naser2/
yuvraj17/microservice-trace-dataset/{sockshop,trainticket}`. Zero data movement.

**Direct cluster access:** the user keeps a live MFA'd SSH master to Trillium in WSL; from this
machine `wsl.exe -d Ubuntu -- ssh trillium bash -s <<'EOF' … EOF` drives the cluster with no
re-auth. NOTE: inline `ssh trillium '…cmd…'` mangles var assignments/semicolons in transit —
**always feed the script over stdin to `bash -s`** (heredoc), never as an argv string.

**On-cluster architecture (resolved constraints):**
- Login node **has internet** — `api.anthropic.com` reachable (http=405 to GET = POST-only, i.e.
  connectivity OK). So the **LLM agent runs on the login node**. Compute nodes = no internet
  (assume), so they do extraction/derive only.
- Whole-node scheduling (`select/linear`, `CR_MEMORY`): a job owns a full **192-core / 767 GB**
  node. `debug` partition (≤1 h, 1234 nodes) schedules instantly — used for extraction.
- Python **3.11** via `module load python/3.11`; **pyarrow is NOT pip-installable** (avail_wheels
  shows `pyarrow 9999` = noinstall stub) — it comes from `module load arrow/19.0.1` on PYTHONPATH.
  Load order matters: **python first, then arrow** (arrow lives in the compiler tree python sets up).
  venv built `virtualenv --no-download .venv`; installed pandas+anthropic `--no-index`, stratatrace
  `--no-index --no-deps` (so pip doesn't try to resolve the pyarrow stub). Helper: `agentic-rca/env.sh`.

## Data path validated end-to-end
Extracted `slow_db` r1 small-modalities to `/scratch/yuvraj17/agentic-runs/` and loaded with
`stratatrace.load_run`: spans 190k / logs 412k / metrics 380k / kernel_l1 3986 / kernel_l3 3986 /
load 4793 rows all read; ground_truth.fault = {target_service: mysql, expected_winning_modality:
kernel} (the blind-spot thesis). **kernel_l2 = 0 rows** — L2 wait-attribution was not derived for TT;
the agent's kernel tool will lean on L1 (sys_lat percentiles) + L3 (digest+deviations). Revisit if
RQ3 needs explicit wait-attribution (derive L2 from L0, or from L1).

## Extraction: small modalities only, offline, one-and-done
`agentic-rca/extract_working_set.sh` (parallel across recipes) + `extract_job.sbatch` select only
spans/logs/metrics/kernel L1-L3 (NOT raw L0 — the agent never needs the multi-GB CTF) from the
`/project` archives into `/scratch/yuvraj17/agentic-runs/<app>/<recipe>/<run>/`. Submitted job
2072606 (debug node, PAR=12/14, RUNGLOB=`*` = all runs both apps). Each `.tar.gz` is a stream so
the full archive must be decompressed to reach the small files (~2.5 min/24 GB); whole node does
all recipes in parallel → minutes. /scratch has 24 TB free; /project archives stay as cold backup.

## Repo reorg (2026-08-08)
Separated concerns without deleting anything (all `git mv`, history preserved):
`agentic-rca/` = agent code only; `transfer/` = all dataset staging/derivation/transfer scripts;
`archive/lmat/` = the LMAT/JSS modeling stack (`microservice/` + vendored `models/`, `dataset/`, JSS
review docs — nothing current imports them); `archive/progress-snapshots/` = superseded dated updates.
CLAUDE.md Map + READMEs updated; `archive/README.md` explains the archive. Collection-script dirs +
submodules left in place (path-referenced everywhere).

## kernel L2 (wait-attribution): NOT derived in the campaign; fixed a UTC-window bug; batch launched
The campaign only ran L1+L3 (`batch_derive_tt.sh` invokes derive_l1+l3, never l2); the one Sock Shop
`kernel_l2.jsonl` was a stray Aug-3 test and is almost certainly empty. Deriving L2 needs the raw L0
CTF (in `/project` archives) + `babeltrace2` — already built on Trillium at `/scratch/yuvraj17/local/`.
**Hard-won bug:** `derive_kernel_l2.py` fed `injection_start_utc` (UTC) to `babeltrace2 --begin/--end`,
but bt2 interprets AND renders timestamps in `$TZ` — the collector traces are stamped in the VM's
**local tz (EDT, UTC-4)**, so the window landed ~4h off the trace → **0 events, n_tids=0** (silent
empty output). Fix: force `TZ=UTC` on the bt2 subprocess (committed in derive_kernel_l2.py). Validated
on a compute node: `dependency_outage` → `ts-travel-service` 100% off-CPU-io-wait (blocked on the dead
`ts-seat-service`), seat 98% — correct dependency-outage kernel signature.
**Cost facts:** compute node ≫ login node (login throttles long CPU; ~50min→~7min per pass); trace is
dense (~2.5M events/s → 7.7M events in a 3s slice); `$SLURM_TMPDIR` = `/dev/shm` 566 GB (fast). Batch
policy: full-node `compute`, `PAR=7`, `MAXSEC=60` (first 60 s of the steady injection — rate-based
wait % are stable), per-recipe staging. Job **2072784** launched for BOTH apps (~7-8 h); writes
`kernel_l2.jsonl` next to each run in `/scratch/yuvraj17/agentic-runs/`. This makes TT and SS identical
(L1+L2+L3) and corrects SS's missing L2 too.

## P0 status (see todolist.md)
Done: env, configurable model (`config.py`, default Claude, `RCA_PROVIDER`/`RCA_MODEL`), data
access (on-cluster extraction). Deferred: MSR dataset paper (2nd priority), baselines (statistical
+ CARE/RCAEval, later), Naser direction-confirm (gate, before heavy build). Tool interface: in-process
tools for the study runner, MCP server as the interactive/demo face. Next: P1 tool layer over the
loader + agent loop, then P2 sanity gate (20 incidents @ 100% telemetry).
