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

## All 15 new recipes written; the 5 code defects verified end to end

### The ten fault recipes

`F_concurrency` lock_contention, priority_inversion, deadlock ·
`G_resource_leak` fd_exhaustion, conn_pool_exhaustion ·
`H_security` resource_abuse, data_exfiltration, fork_storm ·
`I_configuration` dns_delay, nagle_delayed_ack

Same shape as every v1 recipe. Programs live in `faults/workloads/` and run in CPU-capped
containers beside the application, like `noisy_neighbor`. `workload_start` fails loudly if the
container dies on startup, because a fault that never ran produces a **mislabelled** run and
nothing downstream can tell.

### The five code defects: 5 passed, 0 failed

| Defect | Control | With defect | |
|---|---|---|---|
| `code_event_loop_block` | 95 ms | **3695 ms** | 38.9x |
| `code_serial_awaits` | 97 ms | 1524 ms | 15.7x |
| `code_lock_across_io` | 6 ms | 37 ms | 6.2x |
| `code_n_plus_one` | 7 ms | 37 ms | 5.3x |
| `code_unbounded_cache` | — | — | memory is the signal |

All measured against `STRATA_BUG=none` **on the same image**, so the comparison isolates the
defect rather than the rebuild.

### Four measurements were wrong before one was right

This is the part worth remembering. `code_lock_across_io` was reported as doing nothing four
times, and each time the fault was in the measurement:

| Attempt | Why it saw nothing |
|---|---|
| sequential curl | a lock costs nothing when one request is in flight |
| curl via the front end | the proxy added ~35 ms, swamping a 1.7 ms critical section |
| `xargs -P` with curl | 300 process spawns dominated; on and off differed by 1 ms |
| threads, no keep-alive | 25 ms per connection hid the whole serialised cost |

Only one process, real threads and reused connections could see it — and then it was 6.2x.

The instinct on a 1.00x result is to tune the defect or drop it. That would have thrown away a
correct defect four times over. **Before believing a null result, check the measurement can
detect the thing at all.**

### Three infrastructure bugs the smoke run exposed

- **Remove-then-create left the stack broken.** The first version did `docker rm -f` then
  `docker run`; when the run failed the front-end was simply gone, and the containers it did
  create had no compose labels so compose then refused to recreate them. Now compose owns the
  swap via a one-service override file, and a failure leaves the previous container running.
- **Compose renames containers it cannot remove.** After a failed recreate the old container
  becomes `0425f955070a_docker-compose_front-end_1`. Looking up the exact name then finds
  nothing and reports "did not stay up" for a healthy service — that turned three working
  defects into failures in one run. The container is now resolved through compose itself.
- **A green result on zero evidence.** A mangled `sed` returned an empty p50, every comparison
  became an empty-operand error, and the run printed "0 passed, 0 failed / every defect builds,
  serves and measurably misbehaves". Guarded so an empty measurement can never read as a pass.

### Anchored injection, not patch files

`inject_defects.py` inserts at exact anchor strings and refuses if one is missing or ambiguous.
It earned that on the first run: the front-end anchor was wrong (the real signature is
`helpers.simpleHttpRequest = function(...)`, not an object member) and it stopped rather than
half-applying. Cost: one check cycle, zero builds.

---

## Smoke-testing the ten new fault recipes

Nine passed first time with real evidence: lock_contention 36,073 acquisitions in 10 s,
priority_inversion 115 high-priority waits at 86 ms mean, deadlock 6 stuck pairs,
conn_pool_exhaustion 400 connections held, resource_abuse 29.4 M hashes + 3 beacons,
data_exfiltration 839 MB at 41.9 MB/s, fork_storm 2000 forked / 200 live, dns_delay rule
present, nagle_delayed_ack median 99.48 ms against p95 100.66 ms.

`fd_exhaustion` failed, and then failed twice more. Each failure was a different mistake and
all three are worth keeping.

### 1. The mechanism could never have worked

The recipe ran a loop inside the container taking descriptors until EMFILE. **RLIMIT_NOFILE is
per process.** A helper exhausting its own descriptors tells the service nothing — the service
keeps its own budget. The only shared ceiling is the system-wide file-max, in the millions, and
not reachable safely beside a live application.

The same run also showed the target has no bash, so the `exec -a` the loop depended on did not
exist there either. Two independent reasons one recipe could not do its job.

Measured idle use while diagnosing: front-end 21 descriptors (limit 524288), catalogue 9,
carts 4 (limit 1024).

### 2. A check that fails on SIGPIPE reports a working fault as broken

The replacement lowered the service's own limit, and the smoke check was
`fd_exhaustion.sh status | grep -q 'limit: (64|256)$'`. It failed on a VM where the limit
really was 64.

`grep -q` exits at the first match, the script died writing its second line, and `pipefail`
turned that into a failed check. Same class as the pilot's exit 141.

`dns_delay` had the identical shape and passed only by luck — iptables writes its whole output
in one go before grep can exit. A check whose verdict depends on timing is not a check. Both
are now functions that capture first and match second.

### 3. The measurement asked for the wrong symptom

Fixed check, limit applied, and still: `errors=0` under 120 concurrent requests.

Not a dead fault. Node does not refuse the connection — the kernel completes the handshake into
the listen backlog and the app accepts as descriptors free up. The requests get **slow** rather
than failing: p95 went 95 → 590 ms with the cap on. A check keyed on errors would have thrown
away a working fault, the mirror image of mistake 2.

What is true regardless of how the application reacts is that the descriptor count reaches the
ceiling. That *is* the fault, so that is what `prove` measures now: drive load, sample
`/proc/<pid>/fd`, report peak against limit.

### 4. Applying the limit by recreating the container pollutes the run

This one is a methodology problem, not a bug, and it would have shipped in the dataset.

The compose-override version worked, but it restarts the service in the middle of a traced run.
A restart is an enormous event in the kernel stream — process exit, process start, every
descriptor closed and reopened. The signature we would then be studying could be the restart
rather than the exhaustion, and nothing downstream could separate them.

`prlimit` changes RLIMIT_NOFILE on the live process. No restart, nothing recreated, and the
only thing added to the trace is the fault.

### 5. "Idle" measured once, straight after load, is not idle

First prlimit run set the cap from a single reading of 147 for a service that sits at 21 — the
previous probe's connections were still closing. Cap came out at 155 and the fault barely bit:
peak 148 against a ceiling of 155.

Sockets in flight only ever *add* to the count, so idle is now the minimum across several
seconds.

### What this cost and what it bought

Five rounds on one recipe. Every round was caught by a check that asked the fault to prove
itself, rather than by trusting that `inject` exiting 0 meant anything. Nine recipes passed
that same bar first time, so the bar is not the problem — the recipe was.

The baseline number worth keeping: under 150 concurrent requests the Sock Shop front-end peaks
at **151 descriptors** against its stock limit of 524288. That is why aggressive (idle + 8)
bites and why a fixed number tuned on one service would be wrong on the other application.

## Two things now shared instead of duplicated

- `compose_stack` in `fault_lib.sh` is app-aware (`STRATA_APP`), so a recipe built on it works
  on either application. A recipe that only speaks Sock Shop's compose files cannot give both
  apps the same matrix, which is the entire point of the v2 design.
- `code_defect_lib.sh` had its own copy of the 7-file invocation and now calls `compose_stack`.
  Two copies of an ordering that matters is how the v1 drivers drifted into two different
  matrices — the reason Sock Shop has 50 runs and Train Ticket 43.

## Corrected: the Nagle stall is ~100 ms, not 40 ms

Measured on the VM: median 99.48, p95 100.66. The textbook 40 ms is the BSD delayed-ACK timer;
Linux uses a quantised minimum RTO and lands near 100 ms on a Docker bridge.

The recipe writes `expected_stall_ms` into ground truth, so quoting 40 ms from memory would
have shipped a wrong threshold with the dataset. Corrected in the recipe, the workload
docstring, `FAULT-CATEGORIES-V2.md` and `COLLECTION-PLAN.md`.

The magnitude is platform-dependent, so the text now leans on the property that is not: 99.48
median against 100.66 p95 is barely 1 ms of spread, which no queue can produce.

## Open: the new recipes are proven on Sock Shop only

`stratatrace-tt` exists but is stopped and was never bootstrapped, so none of the ten has run
against Train Ticket. They are written to be app-independent — workload containers plus
auto-detected network — but "written to be" is not "shown to be", and that distinction is what
this whole day was about.

`CAMPAIGN_NEW_FAULTS` stays empty until they pass a Train Ticket smoke run too.

---

## The smoke test was passing faults that occupied nothing

After fd_exhaustion, I asked the same question of every other recipe: **is the evidence coming
from the thing being attacked, or from the thing attacking it?** Two recipes failed that
question, and one of them had already passed the suite.

### conn_pool_exhaustion held 400 connections and occupied zero

Measured on the VM while the workload reported "still holding 400/400":

| | |
|---|---|
| `max_connections` | 151 |
| `Threads_connected` | **3** |
| `Aborted_connects` | **750** |
| application | HTTP 200 |
| a fresh external connection | succeeded |

It held raw TCP sockets. MySQL sends its greeting, waits for an auth packet, and aborts the
connection when none arrives — **a pre-auth socket never counts against `max_connections`**. And
`getpeername()` still succeeds on a locally-open socket, so the workload's "still holding
400/400" was simply false.

It passed its smoke test because the evidence check matched the workload's own log line. That
is the worst failure mode this project has: a run labelled as a fault that never happened,
undetectable downstream.

Fixed by logging in properly, proving liveness by *using* each connection, and asking the
server for `max_connections` rather than assuming 151. After:

```
REFUSED after 149 connections: (1040, 'Too many connections')
server reports Threads_connected=152/151
new external connection: ERROR 1040 (HY000): Too many connections
after cleanup: Threads_connected 3
```

This needs a MySQL driver, so workloads now run `stratatrace-workload:v1` instead of stock
`python:3.12-slim`. `cryptography` is in the image because MySQL 8 (Train Ticket) defaults to
`caching_sha2_password` — without it the recipe would work on Sock Shop and fail on Train
Ticket, the exact asymmetry v2 exists to remove.

### dns_delay works, but reaches less than its name suggests

| lookup from inside a container | before | during |
|---|---|---|
| external (`example.com`) | 52 ms | **2555 ms** |
| internal (`catalogue`) | 52 ms | 50 ms |

Docker's embedded resolver answers container-to-container names inside the network namespace,
so they never leave as a UDP/53 packet and an OUTPUT rule cannot see them.

So this is **not** "service discovery is broken" — inter-service resolution is untouched. It is
"anything reaching outside the cluster stalls". A blueprint reading it as service discovery
failing would key on something that never happened.

Its check was `iptables -S | grep --dport 53` — evidence about what *we* did, not what the
system does. Same mistake as conn_pool_exhaustion. It now times real lookups.

Side effect worth knowing: the host's own resolution fails during the window too (`sudo` logged
"unable to resolve host"). Harmless, but it means host-side measurements inside an injection
window are suspect.

### The two that were fine, checked rather than assumed

- **lock_contention** genuinely reaches the kernel: **201,149 futex syscall events in 5 s**
  across 17 threads, counted with LTTng itself. Uncontended mutexes never leave userspace, so
  this was a real risk, not a formality.
- **nagle_delayed_ack** carries its own control in the same run: stalled median **99.30 ms**
  against `TCP_NODELAY` at **0.51 ms**.

### The rule this produced

A recipe's evidence must come from the system, not from the recipe. Three of ten checks were
reading the injector's self-report, and two of those three were reporting fiction.

## Train Ticket VM bootstrapped

49 containers up. Two measurements that immediately changed the plan:

- The network is **`trainticket_my-network`**, not `trainticket_default`.
- `ts-gateway-service` sits at **125 descriptors at idle** against a 524288 limit. The fixed
  `nofile=64` that suited Sock Shop's Node front-end (21 idle) would have killed it outright —
  which is exactly why fd_exhaustion now measures before it sets.

Also caught before running: fd_exhaustion's Train Ticket probe pointed at `:8080/index.html`,
which nginx serves as a static file without ever touching the gateway. The target's descriptor
count would not have moved and the fault would have looked dead. It goes through `/api/v1/*`
now.

The Sock Shop bootstrap's two hard-won fixes were missing from the Train Ticket one and are now
ported: `depmod -a` with a real failure gate (the old code was `modprobe || echo "(deferred)"`,
which carries on with no kernel tracing at all), and `python3-matplotlib` (v1 produced zero
verification images on Sock Shop because of its absence). Plus the LTTng 2.15 PPA, so both VMs
run the same tracer — comparing two applications across two tracer versions would put a
confound under every result.
