# All seven blueprints on v2 — 136 runs, two applications, kernel traces only

Measured 7 September 2026. Job `2274747`, 1 hour on one 192-core node. 136 evidence packs,
**zero measurement failures**, seven rules evaluated on every run.

Every number comes from the LTTng kernel trace and nothing else — no spans, logs or metrics.

## The raw scores

| blueprint | recall | false fires | Sock Shop | Train Ticket |
|---|---|---|---|---|
| `host-cpu-saturation` | **10/10 (100%)** | 0/126 | 5/5 | **5/5** |
| `network-path-degradation` | 22/26 (85%) | 2/110 | 13/13 | 9/13 |
| `cpu-contention-co-tenant` | 8/16 (50%) | 0/120 | 8/8 | 0/8 |
| `datastore-wait` | 9/22 (41%) | 1/114 | 8/11 | 1/11 |
| `service-cpu-throttle` | 5/16 (31%) | 0/120 | 5/8 | 0/8 |
| `service-memory-cap` | 3/16 (19%) | 0/120 | 1/8 | 2/8 |
| `host-disk-saturation` | 1/10 (10%) | 0/126 | 1/5 | 0/5 |

**False fires are almost absent — 3 in 826 opportunities.** The library is conservative to a
fault. Its problem is silence, not noise.

## Not every miss is the blueprint's fault

A fault the campaign itself could not confirm is one a blueprint is *right* to decline. Cross-
checking each non-fire against that run's own `verification.json` splits the 58 misses:

| | count | |
|---|---|---|
| **real misses** — campaign confirmed the fault, blueprint silent | **36** | the rules' problem |
| **defensible** — the fault was never confirmed either | 22 | not the rules' problem |

The 22 are Train Ticket `slow_db` (10), `svc_cpu_cap` (8) and `svc_net` (4) — all already known:
`svc_cpu_cap` has 60x headroom on Train Ticket and never binds (CAMPAIGN-ISSUES 12), and
`slow_db`/`svc_net` verdicts were never calibrated there (issue 13).

**Corrected recall: 58/94 = 62%**, not 50%.

## The result worth leading with

**On Train Ticket `anomaly_net`, the blueprint fired 8/8 while the campaign's metric check could
only confirm 4/8.**

Those 4 are the runs recorded as `no_metric_signature` — netem adds latency, and Train Ticket's
services expose no latency histogram, so Prometheus is blind to them by construction. The kernel
trace is not. The blueprint found the fault in every run, including all four metrics could not
see.

That is the dataset's whole thesis, measured: a modality that sees what another cannot.

## Where the rules genuinely fail

**36 real misses, concentrated in three blueprints:**

| blueprint | real misses | note |
|---|---|---|
| `service-memory-cap` | 13 (7 SS, 6 TT) | claimed **4/4** when built (B4); scores 3/16 here |
| `host-disk-saturation` | 9 (4 SS, 5 TT) | its first real test — it had never run before, because the packs carried neither signal |
| `cpu-contention-co-tenant` | 8 (all TT) | the `CONTENDED = 0.55` clause, diagnosed in the CPU-family report |
| `datastore-wait` | 3 (SS) | |
| `service-cpu-throttle` | 3 (SS) | |

`service-memory-cap` and `host-disk-saturation` are the two built most recently and tested least.
Both were validated on a handful of v1 runs; neither survives 16 and 10 runs on two applications.

## The pattern under all of it

| | Sock Shop | Train Ticket |
|---|---|---|
| fires on confirmed faults | **41/58 (71%)** | **17/58 (29%)** |

Every threshold in `blueprint_decide.py` was measured on Sock Shop v1. The library scores 71% on
the application it was built from and 29% on the other. `host-cpu-saturation` is the sole
exception, and it is the one rule keyed on a quantity with a physical ceiling — utilisation
cannot exceed 1.0, so 0.95 means the same thing on any machine.

**That is the transferability rule from `LATENCY-CAUSES.md` (line 324) applied to the whole
library at once**, and most of it does not pass.

## Selection is not the bottleneck — silence is

| blueprints fired per run | runs |
|---|---|
| none | **76** |
| exactly one | 59 |
| two (ambiguous) | 1 |

Of the 76 with no verdict, 20 are `normal` and correctly silent. **56 fault runs got no answer
at all.** Only one run was ambiguous.

This changes the priority set on 4 September. The v1 finding was that all four broken runs came
from *the wrong blueprint being picked*, so `Z1` (fix selection) was deferred until the library
improved. On v2 the failure mode is different: blueprints do not fire at all. Fixing selection
would not have moved a single one of these 56 runs.

## Reproducing

```bash
python blueprints/lib/v2_tasks.py --families normal,slow_db,noisy_neighbor,svc_cpu_cap,\
anomaly_net,svc_mem_cap,anomaly_cpu,anomaly_disk,svc_net --out blueprints/lib/tasks-v2-latency.txt
sbatch blueprints/lib/cluster-v2_all.sbatch
```

Per-run: `results/v2-blueprints-all/{packs,verdicts,scored_all.json}`.

## Next, in order of what the evidence says

1. **`service-memory-cap` and `host-disk-saturation` need re-deriving, not tuning.** 13 and 9
   real misses. Both were built from a handful of runs; the thresholds should be re-measured
   across all 16 and 10, both applications.
2. **Drop the `busy` clause from `cpu-contention`** — recovers 8 Train Ticket runs, no new false
   fires (see the CPU-family report).
3. **Calibrate Train Ticket `slow_db` and `svc_net`** so those 14 runs become scorable at all.
4. **Re-order `Z1`.** Selection was deferred as the last job. These numbers say it is not the
   bottleneck; 56 runs produced no candidate to select between.
