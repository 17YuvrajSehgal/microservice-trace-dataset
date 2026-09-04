# StrataTrace v2 — the one-shot collection spec

Written 4 Sept 2026. Answers the six conditions set for this campaign.

**The rule for this document: we do not get a second run.** So everything below is either
measured from v1, read out of our own scripts, or explicitly flagged as unverified.

---

## 1. The honest warning up front

You asked me to be 100% sure. I can be 100% sure about the **gaps we already know**, because
those are measured. I cannot be 100% sure there is no unknown gap — that is what a pilot is
for.

**So the plan has a gate.** Run 2 pilot runs, check 8 things, and only then launch the
campaign. The pilot costs about 20 minutes. Skipping it is the only way this goes wrong in a
way we cannot recover from.

---

## 2. What must change, and the one thing that breaks "keep it identical"

You asked to keep the VM configuration the same so results do not vary. Keep these **exactly**
as v1:

| Setting | Value |
|---|---|
| Machine type | same as v1 (`n2`, same vCPU/RAM) |
| Zone | `us-east1-d` (v1 moved b→d when b ran out of n2 capacity) |
| OS | Ubuntu 24.04 |
| LTTng | 2.15 |
| Docker | 27+ |
| Buffers | 8 MB × 32 sub-buffers per CPU (unchanged) |
| Windows | baseline 60 s, injection 120 s, recovery 60 s (unchanged) |
| Load | 150 users steady, 300 burst (unchanged) |

**But one thing genuinely cannot stay identical.** Turning on memory tracepoints and namespace
contexts adds tracing work. That changes overhead, and overhead can move the very numbers we
measure.

So be clear about what v2 is: **v2 is internally consistent, and is not numerically comparable
to v1 run-for-run.** That is fine — you said re-run everything — but it means:

- do not mix v1 and v2 runs in one analysis
- the pilot must measure how much the overhead moved

If the pilot shows the added tracing changes the CPU picture materially, the fallback is to
run the memory tracepoints only on the four memory-relevant families and say so.

---

## 3. Everything we only realised later — the full list

This is the part that matters most. Each one is a thing we could not fix without re-running.

### Already fixed in the collector (committed)

| # | Gap | Why it cost us |
|---|---|---|
| 1 | **No container attribution** | `procname` is ambiguous — Sock Shop runs several Go services all called `app`. **Three blueprints can say a fault is happening but not which service.** Fixed by adding namespace ids (`cgroup_ns`, `pid_ns`, `net_ns`, …) to every kernel event. We were *already* recording each container's namespace map in metadata — we had the lookup table and were missing only the key on the event |
| 2 | **Event loss never recorded** | `lttng stop \|\| true` threw away the discarded-event count, which LTTng reports there and nowhere else. A run that dropped a third of its events looks identical to a clean one, and every ratio from it is wrong. Now written to `meta/event_loss.json` |
| 3 | **Enabled events never recorded** | Nothing said which tracepoints were actually on. Finding out meant opening the trace |
| 4 | **Memory tracepoints off** | Our 3 wrong answers are all memory faults called noisy neighbours. Both indirect routes died the same way — block latency (F18) and interrupt time (F20) each worked on one app and failed on the other. **No route left except recording the memory layer** |
| 5 | **No cgroup counters** | `cpu.stat` (`nr_throttled`), `memory.events` (`max`, `oom`), `memory.stat` (`pgscan`/`pgsteal`), `io.stat` state directly what a blueprint currently infers — and give per-run ground truth that does not depend on our analysis being right. Free to read, no tracing cost |

### Still open — decisions needed before launch

| # | Gap | What to do |
|---|---|---|
| 6 | **Memory profile size** | `KERNEL_MEM=1` now enables a *targeted* set (`vmscan_*`, `writeback_*`, `compaction_*`, `migrate_*`) rather than the `kmem_*` firehose. The reclaim signal lives in `vmscan_*` and is far cheaper. `KERNEL_MEM=full` keeps the old behaviour. **Pilot must measure both size and event loss** |
| 7 | **`lock_*` availability unknown** | One command on the VM: `lttng list --kernel \| grep -i lock`. Decides whether kernel lock contention is collectable at all. Same for `power_*` (CPU frequency) |
| 8 | **The two campaign drivers disagree** | Sock Shop's `CORE_FAULTS` lists 8 families; Train Ticket's lists 11. **Neither covers all 12.** This is exactly why the run counts are uneven. v2 uses one matrix for both |
| 9 | **`queue_backlog` does not exist on Train Ticket** | Not an omission — `FAULTS-TT.md` records that TT has **no message broker**; its booking path is synchronous REST. The planned remodel is MySQL connection-pool exhaustion via a toxiproxy connection cap. **That recipe was never written.** Without it the two apps can never be identical |
| 10 | **No compound faults** | All 12 recipes inject one thing. Naser asked for combined causes. Every look-alike pair we know is a candidate |

---

## 4. Why the run counts are uneven today

Measured from the stored runs:

| Condition | Sock Shop | Train Ticket |
|---|---|---|
| `error_storm_aggressive_steady` | 2 | **0** |
| `normal_none_steady` | 3 | **1** |
| `queue_backlog_aggressive_steady` | 3 | **0** |
| everything else | matched | matched |
| **total** | **50** | **43** |

Two different reasons, and they need different fixes:

- `error_storm` steady and `normal` steady: **in the TT matrix, never completed.** Just run them.
- `queue_backlog`: **cannot be run on TT as written.** Needs the new recipe (gap 9).

---

## 5. The v2 matrix — identical on both applications

Per application:

| Group | Families | Variants | Repeats | Runs |
|---|---|---|---|---|
| Core | all 12 faults | aggressive / steady | **5** | 60 |
| Healthy | normal | steady | 5 | 5 |
| Healthy | normal | burst | 5 | 5 |
| Intensity | noisy_neighbor, slow_db, svc_cpu_cap, svc_mem_cap, anomaly_mem | subtle / steady | 3 | 15 |
| Workload | slow_db, error_storm, anomaly_net | aggressive / burst | 3 | 9 |
| **Total per app** | | | | **94** |
| **Both apps** | | | | **188** |

**Repeats go from 3 to 5.** v1's thinnest family had **2 runs**, and it now carries a
blueprint threshold. Five is the cheapest insurance we can buy against that.

Rough cost, to be confirmed by the pilot:

| | Estimate |
|---|---|
| Time per run | ~6 min (240 s of run + setup/teardown) |
| Time per app | ~9.5 h |
| Time, both apps | **~19 h of VM time** |
| Size per run | ~2.2 GB compressed in v1; **pilot must measure with memory events on** |
| Size total | ~600–800 GB, if memory tracing roughly doubles it |

Compound faults are **not** in the count above. If we want them, add 4 pairs × 3 repeats ×
2 apps = 24 runs, and they need a wrapper that runs two recipes at once.

---

## 6. The pilot gate — 8 checks before spending the campaign

Two runs: one `normal`, one `svc_mem_cap` (the fault with the thinnest evidence and the one
most affected by the new memory tracepoints).

| # | Check | How | Fail means |
|---|---|---|---|
| 1 | Namespace contexts present | `meta/lttng_enabled_kernel.txt` lists `cgroup_ns`, `pid_ns`, `net_ns` | attribution fix did not apply — stop |
| 2 | Contexts actually on events | decode 100 events, confirm the ns fields appear | context accepted but not recorded — stop |
| 3 | Container map usable | namespace inode in the trace matches `meta/proc_*_start.txt` | the join does not work — stop |
| 4 | **Zero events discarded** | `meta/event_loss.json` says `clean: true` | buffers too small for the new load — raise them before the campaign |
| 5 | Memory tracepoints present and useful | `vmscan_*` events exist, and rise for the memory fault | the targeted set is too narrow — switch to `KERNEL_MEM=full` |
| 6 | cgroup counters captured | `meta/cgroup_*_start.txt` has `memory.events` with a non-zero `max` for the capped container | wrong cgroup path — fix before the campaign |
| 7 | Size per run | measure the compressed run | multiply by 188 and check the disk plan |
| 8 | Overhead delta vs v1 | compare host CPU in the healthy run against a v1 healthy run | if it moved a lot, restrict memory tracing to 4 families |

Checks 1–6 are pass/fail and block the campaign. 7 and 8 are measurements that change the
plan rather than stop it.

---

## 7. Packaging for Trillium

Each run becomes one self-describing bundle, so moving it is one command and nothing is
ambiguous later:

```
<family>/<run_id>/
  kernel/        CTF streams, gzipped
  ust/           the span relay
  otlp/          spans.jsonl, byte-sliced to this run
  logs/          per-container docker logs
  metrics/       Prometheus range dumps
  meta/          runinfo, clocks, docker inspect, ps, cgroup counters,
                 lttng_enabled_kernel.txt, event_loss.json
  ground_truth.json
  verification.json     did the fault actually move its target metric
  MANIFEST.json         run id, app, family, intensity, workload, repeat,
                        v2 profile, event-loss verdict, sizes, sha256 of each part
  SHA256SUMS
```

One campaign-level `campaign_manifest.csv` carries every run's verification verdict **and its
event-loss verdict**, so a bad run is visible before anyone analyses it.

---

## 8. What I need from you

| When | What |
|---|---|
| Before the pilot | VM access, and the answer to `lttng list --kernel \| grep -i lock` |
| Decision needed | do we write the TT `queue_backlog` replacement (gap 9)? Without it the apps cannot be identical |
| Decision needed | do we want compound faults in v2 (gap 10)? +24 runs, needs a new wrapper |
| Before launch | confirm the disk plan once the pilot reports run size |

---

## 9. Order of work

1. Create the VM with the v1 configuration
2. `vm_bootstrap.sh`, then `run_gate.sh gate01` — proves the stack is healthy
3. **Pilot: 2 runs, 8 checks**
4. Fix anything the pilot finds
5. Sock Shop campaign (94 runs, ~9.5 h), packaging as it goes
6. Transfer to Trillium, verify checksums
7. Redeploy as Train Ticket, repeat
8. Final audit: every family has 5 runs on both apps, and no run reports event loss
