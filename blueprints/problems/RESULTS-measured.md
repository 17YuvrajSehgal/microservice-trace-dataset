# Measured discrimination between the two blueprints

Everything below was measured from the **raw LTTng trace (L0)** with babeltrace2, on two
labelled Sock Shop runs. Each row is a signal; each family is the other family's control.

## The two signals, and how they cross

| Signal (from L0) | Co-tenant CPU contention | Slow datastore |
|---|---|---|
| **Runqueue delay**, busiest app process p95 | **7.12×** (n=48,886) | 0.97× |
| Runqueue delay, median across high-volume processes | **1.78×** | **0.84×** |
| Runqueue delay of the datastore | — | 1.09× |
| **Datastore `poll` duration** p95 | **1.12×** (n=45,337) | **36.83×** (n=17,245) |
| Largest inflation of *any* syscall | 3.95× | 36.83× |
| **Trace convergence** | **none** (max 1.7×, 0 slow edges) | **717.7×**, terminal |

The same two measurements, on the same components, point in opposite directions. That is
what makes these blueprints mutually exclusive rather than merely different.

## The verdict script routes itself

`dependency_verdict.py` run on both, unchanged:

```
SLOW DATASTORE  -> YES
  mysqld blocked in poll for 36.83x its baseline (p95 15.959 -> 587.698 ms, n=17245)
  runqueue delay stayed flat (max 1.59x, median 0.84x), so it is not short of CPU
  slow call edges converge on catalogue
  NOTE: traces name catalogue but the kernel shows mysqld is the one blocked -
        catalogue is a victim, and mysqld emits no spans

CO-TENANT       -> NO
  no socket-waiting syscall inflated by 5.0x or more (largest was 3.95x)
  runqueue delay inflated up to 7.12x (median 1.78x) - the processes are short
  of CPU. Use the CPU-contention blueprint
```

## Why raw L0 and not the derived layers

The derived L2 record could not support either blueprint:

| | Derived L2 | Raw L0 |
|---|---|---|
| CPU contention | `runnable_wait` **1.6%** — and never above 4% in *any* family | runqueue delay **7.12×** |
| Datastore wait | `off_cpu_io_wait` **99.4%** — but 98–99% in *every* family | `poll` duration **36.83×** vs 1.12× control |
| Host-attributed faults | **no culprit record at all** (5 families) | full trace available |

L2 reports *shares of wall time*, which idle waiting dominates, so everything looks the
same. L0 gives *per-event latencies*, where the effect is unmistakable. This is also the
easier story to tell: the agent reads the original LTTng trace, not a derived summary.

## Reproducing

```bash
bash /scratch/yuvraj17/extract_l0.sh sockshop noisy_neighbor noisy_neighbor_aggressive_steady_r1
bash /scratch/yuvraj17/run_rq.sh    noisy_neighbor_aggressive_steady_r1 rq.json
bash /scratch/yuvraj17/run_block.sh slow_db_aggressive_steady_r1 mysqld,app blocking.json
bash /scratch/yuvraj17/run_conv.sh  slow_db slow_db_aggressive_steady_r1 conv.json
```

**Trace-reading gotcha:** the metadata is CTF 2 (JSON preamble). babeltrace 2.0.x fails with
an invalid-metadata error; use 2.1+ via `/scratch/yuvraj17/bt21.sh`, which puts its own lib
directory first (otherwise the binary loads the old .so and dies on a missing symbol).

## Honest limits

- **One run per family so far.** The gaps are large (7× vs 1×, 37× vs 1.1×), but repeats
  across intensities and the second application are still owed.
- **Traces name the victim.** Convergence lands on the datastore's caller because the
  datastore emits no spans. Recorded in the blueprint as a known limitation, not hidden.
- Attribution is by process name, which is sufficient on this application but ambiguous on
  the Java-heavy one, where every service reports the same comm.
