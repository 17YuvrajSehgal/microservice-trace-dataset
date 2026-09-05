# 04-09-2026 — A1: the latency cause list

Task from the 2 Sept meeting. Naser asked for 5–10 causes of latency, single and combined, and
for each whether kernel traces can see it. He said to use AI for the list, since it is
textbook knowledge.

Output: `blueprints/docs/LATENCY-CAUSES.md`.

## The choice that shaped it

The list of causes is textbook, as asked. **The "can we see it" column is not.** Every answer
points at one of our own findings across 109 runs, and anything unmeasured says so.

Doing it the other way would have been faster and useless. We already know from F17 that a
signal which "should" work can lose to a fault nobody thought to test it against.

## Where we stand: 11 causes

| Can kernel traces see it | Count | Which |
|---|---|---|
| Yes | 6 | CPU wait (3 kinds), disk, network loss, downstream wait, container memory cap, interrupt load |
| Partly | 1 | lock contention |
| One app only | 1 | host memory pressure |
| Proved impossible | 2 | service stops answering, queue backlog |
| Never tried | 1 | CPU frequency, priority, NUMA |

## Two things the list changed

**Container memory cap moves from impossible to buildable.** It was filed Tier C, "needs logs,
OOM-kill is the tell". F20 shows interrupt time separates it on **both** apps — 6.2x on Sock
Shop, 3.2–4.3x on Train Ticket, against a ceiling of 1.8x. That is a blueprint we can write
now.

Caveat kept in the doc: the model already gets this fault right 2 times in 3 unaided. So it
helps the rule engine, not the with/without story.

**Lock contention is further along than expected, but aimed at the wrong locks.**

Good: total lock wait moves for nothing we inject (1.38x / 1.11x across all families, F22). The
negative control exists before the blueprint does — the reverse of the F17 mistake.

Bad: we only see **user-level** locks, via `futex`. Naser asked for **kernel** locks. `lock_*`
tracepoints are not in our profile and usually need a kernel built with lock debugging.

**Recorded as unverified rather than assumed.** The VM is stopped; one `lttng list --kernel`
settles it. That check is now step 1 of B1, because it decides what B1 even is.

## The trap already found, before writing anything

Total futex wait on the first probe was **408 seconds per second of wall clock**. Java alone
waited 6,684 s over 22,036 calls — about 300 ms each. That is thread pools **parked waiting for
work**, not contention.

Contention has the opposite shape: many waits, each short. So the lock blueprint must key on
the shape and never the total. Written into the doc so nobody rediscovers it.

## Combined causes

Naser asked for these as well, and they turned out to be the most useful section. All five are
measured, and every one is a case where a fault **looks like** a different fault:

- memory cap → 95% packet re-sends, harder than any real network fault (F17)
- CPU cap → lock waits landing on ~100 ms, which is the CFS quota period, not a lock bug (F21)
- memory stress → eats a core, so it reads as a noisy neighbour — our 3 wrong answers
- memory pressure → disk work, so both raise interrupt time (F20)
- slow disk under a database → its callers cannot tell disk from network from a slow query

**The pattern:** the knock-on effect is consistently **larger** than the direct one. That is
the argument for why one signal cannot name a fault, and why E1 specificity testing is not
optional.

## Still open

The 3 wrong answers (memory faults called noisy neighbour) survive. Interrupt time looked like
the fix on Sock Shop and died on Train Ticket. Only route left is re-collecting a few runs with
`KERNEL_MEM=1`, which records reclaim and paging directly instead of inferring them.

## Do we need new collection? Yes — three things

Full list: `blueprints/docs/COLLECTION-PLAN.md`. Written because a new GCP project is being
set up and the machine shape depends on what we intend to collect.

### The three that block work

**1. Memory events (`KERNEL_MEM=1`).** Our 3 wrong answers are all memory faults called noisy
neighbour, and we have tried twice to reach them indirectly — disk latency (F18) and interrupt
time (F20). Both worked on one application and died on the other. There is no third
workaround. The memory layer has to be recorded. 12 runs per app; ~8 GB per run instead of
2–3 GB, so ~200 GB for both.

Do one app first. If the memory layer does not separate memory stress from a noisy neighbour
there, stop rather than spend the second app.

**2. A lock contention positive example.** F22 gave us the negative control for free — total
lock wait moves for nothing we inject. But we have never injected lock contention, so we know
what its absence looks like and not what it looks like. Needs a program, plus its look-alike
(an idle thread pool), because idle parking swamped the total on the first look: 408 seconds
of wait per second of wall clock, which was Java pools parked waiting for work.

**3. Priority inversion and Nagle/delayed-ACK.** Both are cases where every signal we collect
says the system is healthy — no resource is busy, no packet is lost. That is exactly the shape
Naser asked for: the agent alone should fail, the blueprint should win.

### Cheap while the machine exists

- **Compound faults — we have zero.** All 12 recipes inject one thing. Naser asked for combined
  causes. Every look-alike pair we know is a candidate, starting with a CPU cap applied while
  a lock is held.
- Top up `svc_mem_cap` (4 runs total, thinnest threshold in the library) and `anomaly_disk`.
- More healthy runs at varied load. Our thresholds are set by the busiest healthy run, so this
  is the cheapest way to learn whether they are safe or lucky.
- The intensity calibration the VM already owed.

### The split worth knowing before picking machine types

Steps 1–3 need **no microservice deployment**. They are small programs on a plain VM. Only the
memory re-collection and compound faults need the full stack. So two machines may be cheaper
than one: a small one for the programs, the usual shape for the microservice runs.

### One thing to run before planning

`lttng list --kernel | grep -i lock` on the new VM. Naser asked for KERNEL lock contention;
today we can only see user-level locks through futex. That one command decides what B1 is.

## v2 VMs created and the pilot passed

### Where the VMs are, and why not a new project

Project **`teleeporter`**, zone **us-east1-d**:

| VM | Machine | Disks | State |
|---|---|---|---|
| `stratatrace-ss` | 12 vCPU / 40 GB | 200 GB pd-balanced + 1 TB pd-standard | running |
| `stratatrace-tt` | 16 vCPU / 64 GB | 200 GB pd-balanced + 1 TB pd-standard | stopped until SS finishes |

A **new** project starts at 12 CPUs all-regions and 250 GB SSD, so Train Ticket's 16 vCPU
could not be created at all and a 1 TB disk was refused. We never hit this before because
quotas rise with a project's own age and billing history — the v1 project had earned higher
limits over months. It is unrecoverable: its owner account has been deleted.

`teleeporter` already had 32 CPUs / 500 GB SSD / 4096 GB disk on the same billing account,
so nothing had to be requested or waited for.

**Two things are better than v1 by accident.** Both VMs are in the **same zone** — v1 ran Sock
Shop in us-east1 and Train Ticket in us-east4, so a signal that failed to transfer between
applications could equally have been a machine or region difference. That confound is gone.
And disks are split by role: LTTng writes to the fast pd-balanced disk, gzipped runs move to
the pd-standard archive, which counts against a different and much larger quota.

### Two things measured on the VM that changed the plan

- **No `lock_*` tracepoints.** Stock Ubuntu kernels lack the lock debugging they need. Naser
  asked for kernel lock contention; it is not collectable without a custom kernel, so the lock
  blueprint is about **user-level `futex`** locks and says so.
- **`power_cpu_frequency` and `power_cpu_idle` ARE available** and are now in the profile.
  CPU frequency moves from "never tried" to collectable — it was never invisible, we simply
  were not recording it.

### The bootstrap bug that would have wasted the campaign

LTTng 2.15 builds fine on the newer 6.17 kernel, but after the dkms install `modprobe
lttng-tracer` failed and `lttng list --kernel` returned "Failed to list Linux kernel
tracepoints". The build was fine; the **module index was stale**. One `depmod -a` fixed it and
all 233 tracepoints appeared. `vm_bootstrap.sh` now does the depmod, loads the module, counts
the tracepoints, and exits 1 if it cannot.

### Pilot result: 13 passed, 0 failed

Measured on a real 60 s run, all four modalities:

| | |
|---|---|
| kernel | 12 per-CPU streams, 200k+ events decode |
| spans | 253 spans from 6 services |
| logs | 11 containers, 65,506 lines |
| metrics | 429 non-empty series files |
| event loss | **zero discarded** |
| cgroup counters | 14 containers, `memory.events` present |
| clocks | anchors recorded |
| matplotlib | importable — the v1 missing-image cause is fixed |

**The v2 headline feature works.** Every event now carries container identity:

```
sched_waking: { cpu_id = 9 }, { pid = 0, tid = 0, procname = "swapper/9",
  cgroup_ns = 4026531835, pid_ns = 4026531836, net_ns = 4026531833,
  ipc_ns = 4026531839, user_ns = 4026531837 }, { comm = "node", ... }
```

Five of six namespace types attached; only `mnt_ns` is unavailable on this kernel, and adding
each type best-effort meant losing it cost nothing.

### The first pilot said 2 FAILED, and all of it was my checker

Worth recording, because a checker that cries wolf is worse than no checker.

1. **SIGPIPE vs `pipefail`.** `babeltrace2 ... | head | grep -q` returns **141** under
   `set -o pipefail`, because `head` closing the pipe kills babeltrace. The check was *finding*
   its match and reporting failure.
2. **`lttng list <session>` does not print contexts.** Grepping it reported the attribution fix
   as missing while every event carried it. The decoded events are the only authoritative
   answer, and that is what it checks now.
3. **Spans are OTLP**, so the top-level key is `resourceSpans` and `service.name` sits in
   `resource.attributes`. A flat grep reported 0 services on a good file — now 6.

### Size

2.25 GB uncompressed for a 60 s run, so roughly 9 GB for a 240 s campaign run and ~2.8 TB
across 308 runs, gzipping to ~700–900 GB. That fits the 1 TB archive disk.

### The fault pilot: 16 passed, 0 failed, 0 warnings

`svc_mem_cap aggressive`, `KERNEL_MEM=1`, 165 s. This is the run that exercises everything the
healthy run could not.

| | |
|---|---|
| kernel | 12 streams, 200k+ events |
| spans | 768 from 6 services |
| logs | 12 containers, 458,854 lines |
| metrics | 430 series files |
| event loss | **zero** |
| namespace ids on events | cgroup_ns, ipc_ns, net_ns, pid_ns, user_ns |
| memory tracepoints | **firing** (vmscan/writeback seen) |
| power tracepoints | **firing** |
| cgroup counters | 14 containers, `memory.events` present |
| `ground_truth.json` | present |
| **`verification.png`** | **present** |

That last line closes the v1 gap for good: Sock Shop produced **zero** images across 50 runs,
and now produces one on the first fault run attempted.

### Size, measured rather than estimated — and it changes the disk plan

| | |
|---|---|
| 165 s run, memory tracepoints on | **18.9 GB raw** |
| kernel streams gzipped | 18.1 GB → **1.8 GB (10.1x)** |
| a 240 s campaign run | **28 GB raw, 3.9 GB gzipped** |
| 308 runs | **8.5 TB raw, 1.19 TB gzipped** |
| what the 1 TB archive holds | **~259 gzipped runs** |

Two things follow.

**Memory tracepoints roughly triple the volume.** The healthy 60 s run without them was
2.25 GB; scaled to 165 s that would be ~6 GB, against 18.9 GB measured. That is the real cost
of answering the memory question.

**gzip does better than we assumed** — 10.1x on the CTF streams, not the 3–4x written in the
spec. That is what makes this affordable at all.

**But 1.19 TB gzipped does not fit the 1 TB archive.** The campaign cannot simply accumulate
locally. Options, cheapest first:

1. transfer to Trillium incrementally and delete locally as we go (the archive then only needs
   to hold a working window, not the whole campaign)
2. grow the archive disk — `pd-standard` counts against DISKS_TOTAL_GB (4096), so there is
   room without a quota request
3. enable memory tracepoints only on the families that need them, which halves the total but
   reintroduces a profile split

Recommendation: (1) plus (2). Incremental transfer is needed anyway, and growing the disk is
free of quota friction.

### A campaign-duration finding

`audit_alignment.py` took **over 6 minutes** on this run, because it decodes the trace and the
trace is 3x bigger with memory events on. Run inline per run, that is ~30 hours across 308
runs — as much as the collection itself.

The audit does not have to be inline. We keep the raw traces, so it can run on the cluster
afterwards. Worth moving before the campaign starts.
