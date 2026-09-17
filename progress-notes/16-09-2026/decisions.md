# 16-09-2026 — decisions

## 1. The collection VM is deleted. Trillium is the only copy again.

`stratatrace-ss`, its 200 GB boot disk and its 1 TB archive disk are gone. GCP cost for this
project is zero. It existed 14–16 Sept and did exactly one job: re-collect the 54 Sock Shop runs
the audit found unusable.

**Before deleting, I swept the machine for anything that existed only there.** That mattered —
three things were not in the run bundles:

| found | why it would have been lost |
|---|---|
| Prometheus TSDB (179 MB) | per-run `_metrics/*.json.gz` only hold series somebody thought to export |
| `gate01` validation run (1.4 GB) | the proof THIS machine was set up correctly, in `~/traces`, not `/mnt/archive/runs` |
| `fault-state/` (54 dirs), gate/bootstrap logs, 5 custom Docker images | not under the pull path at all |

They are now `provenance_20260916.tar.gz` and `provenance_vm_20260917.tar.gz`.

**Why this nearly went wrong.** I scoped the pull key to a forced command that only exposes
recipe directories under `/mnt/archive/runs`. That is good security and it silently defined what
could be transferred. The run bundles were complete; everything around them was invisible to the
pull. Found only because the question "is everything we need on Trillium?" was asked directly.

## 2. Retired the superseded Sock Shop material

Moved, not deleted, to `superseded-20260917/`: **10 archives (105 GB), 10 extracted trees
(783 GB), 53 derived packs.** `WHY.md` records the reason per family.

Seven were genuinely broken — 5 `code_*` (container restart inside the baseline window),
`anomaly_net` (netem applied before the incident stamp), `dns_delay` (r4 never injected).

**Three were not**: `fd_exhaustion`, `lock_contention`, `deadlock` were `unconfirmed`, not
contaminated. They were retired anyway because a complete verified replacement exists and
leaving both copies side by side invites exactly the mixing this was meant to prevent. That is a
judgement call, and it is written down in `WHY.md` rather than left implicit.

The 783 GB of extracted trees are regenerable from the archives if scratch gets tight.

## 3. The verification took four attempts, and three of them were my own bugs

| attempt | what happened |
|---|---|
| inline on the login node | `nice 19` + idle I/O on a node at load 48 → **0.4 MB/s**; I also started it twice |
| SLURM, debug partition | killed at 55 min with ZERO output — I read each archive twice and piped through `sort`, which buffers until the end |
| SLURM, compute, 3 h | killed again; `--export` does not survive Trillium's sbatch wrapper, so every job verified everything |
| **job array** | **3 minutes, 120 MB/s per node** |

The number that explains it: the 3-hour job burned **7 minutes of CPU on 192 cores**. The work
was never CPU bound and a whole node never helped — it is bound by how fast ONE node pulls gzip
off `/scratch`, and running four archives on that node splits one pipe four ways. One archive
per node fixed it. I spent three submissions tuning reads and buffering before looking at that.

`transfer/verify_archives_array.sbatch` is the version that works, with markers so a re-run only
re-reads what is still in doubt.

## 4. `fd_exhaustion` is an analysis problem, not a collection one

Re-collecting it made the metric verdict *worse* (2/5 → 0/5 confirmed) while proving the fault
always fires: `target_pid_survived_window: false` in **all ten runs**, old and new.

The prlimit caps RLIMIT_NOFILE to about half the descriptors in use; the front-end dies; its
supervisor respawns it WITHOUT the per-process limit, so `container_file_descriptors` CLIMBS
(98 → 446 → 560) against a target expecting `decrease`.

The evidence was in the old ground truth all along. I read the `unconfirmed` verdicts and not
the ground truth underneath them, and recommended a re-collection on that basis. The re-run was
not wasted — it produced 5 clean runs and the proof — but the right fix is the target.

**Open work**: correct the target and re-score. The TSDB in `provenance_20260916.tar.gz` is what
that re-scoring needs, which is the concrete reason it was worth saving.
