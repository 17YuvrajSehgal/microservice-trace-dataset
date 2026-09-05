# Getting from 5 issue types to ~10

Written 4 Sept 2026, after Naser: *"no, latency is only the first step. we will cover around
10 different issue types."*

---

## What we cover today

`fault_catalog.md` already has a taxonomy. Our 12 faults sit in **5 categories**:

| Code | Category | Faults we have |
|---|---|---|
| A | Host resource | anomaly_cpu, anomaly_disk, anomaly_mem, anomaly_net |
| B | Service resource limit | svc_cpu_cap, svc_mem_cap, svc_net |
| C | Application | error_storm, queue_backlog |
| D | Dependency | slow_db, dependency_outage |
| E | Infrastructure / tenancy | noisy_neighbor |

Most of these are **latency** faults. That was the point of phase 1. To reach ~10 issue types
we need about 5 more categories.

---

## The gap, in one line

We have a lot of **"something is slow because a resource is scarce"** and almost nothing else.

Missing entirely: concurrency defects, resource leaks, security/abuse, configuration mistakes,
lifecycle churn, and cascading failure.

---

## Proposed new categories

Each is rated on the two things that matter for a one-shot campaign: **can the kernel see it**
and **how likely is the recipe to work first time**.

### F. Concurrency defects

Naser asked for lock contention by name. This is also where the hardest cases live: nothing
looks busy, so an agent has no resource to blame.

| Fault | Kernel-visible | Recipe risk | Note |
|---|---|---|---|
| `lock_contention` | yes, via `futex` | **low** | negative control already measured (F22) |
| `priority_inversion` | yes, `sched_*` + `futex` | **low** | ~30 lines. Everything stalls, nothing is busy |
| `deadlock` | yes — threads block forever, CPU flat | **low** | distinct from contention: waits never end |

### G. Resource leaks — slow, not sudden

Every fault we have is a step change. Real incidents often creep. A leak looks healthy for
most of the window, which is a genuinely different detection problem.

| Fault | Kernel-visible | Recipe risk | Note |
|---|---|---|---|
| `fd_exhaustion` | **yes, clearly** — `accept`/`socket` start returning EMFILE | **low** — but see below | we record every syscall including its return |
| `conn_pool_exhaustion` | yes — connects queue, then fail | **low** | toxiproxy connection cap; we already run toxiproxy |
| `memory_leak` | partly — reclaim rises late | medium | needs a leaking sidecar; slow to show |

**`fd_exhaustion` was rated "low risk" and took five rounds to get right.** Worth recording,
because the rating was about the *idea*, not the implementation, and the two are not the same
thing:

1. An external process eating descriptors cannot work — **RLIMIT_NOFILE is per process**, so a
   helper exhausting its own budget tells the service nothing.
2. The smoke check used `status | grep -q`, which fails on SIGPIPE and reported a working fault
   as broken.
3. The check then asked for failed requests and got `errors=0` — Node queues in the listen
   backlog rather than refusing, so requests get slow (p95 95 → 590 ms) instead of failing.
4. Applying the limit by recreating the container **restarts the service mid-run**, putting a
   process exit and start into the very trace we are collecting. That is a methodology problem,
   not a bug, and it would have shipped in the dataset.
5. "Idle" measured once, right after load, read 147 for a service that sits at 21.

Final mechanism: `prlimit` on the live process, limit set to measured idle plus headroom, with
the recipe able to prove itself by driving load and watching the descriptor count reach the
ceiling. Sock Shop's front-end peaks at **151 descriptors** under 150 concurrent requests
against a stock limit of 524288.

**`conn_pool_exhaustion` is worth singling out.** `FAULTS-TT.md` already proposed it as the
Train Ticket analogue of `queue_backlog`. Adding it as its own family gives Train Ticket a
saturation fault *and* closes the asymmetry you asked about.

### H. Security and abuse

Naser said in the 2 Sept meeting: *"Mainly performance, but security can be a part of it as
well."* All of these are **benign simulations** on our own isolated VM — a CPU-burn loop, a
bulk transfer between two of our own containers, a bounded process-spawn loop. No malware.

| Fault | Kernel-visible | Recipe risk | Note |
|---|---|---|---|
| `resource_abuse` (mining-style) | yes | **low** | CPU-heavy with a distinctive syscall profile — looks like noisy neighbour but is not |
| `data_exfiltration` | yes — large sustained outbound transfer | **low** | tests whether we can tell *unusual* traffic from *heavy* traffic |
| `fork_storm` | **yes, very** — process creation storm | **low** | bounded spawn loop; `sched_process_fork` is unmistakable |

These matter for the thesis framing: the same blueprint machinery, applied to a different
question. And `resource_abuse` vs `noisy_neighbor` is a genuine look-alike pair.

### I. Configuration and environment

Mistakes, not failures. Nothing is broken; something is set wrong.

| Fault | Kernel-visible | Recipe risk | Note |
|---|---|---|---|
| `dns_delay` | yes — resolution stalls before connect | **low** — but see below | slow or unreachable resolver |
| `nagle_delayed_ack` | yes — fixed stalls, measured ~100 ms | **low** | famous, ~30 lines, everything looks healthy |
| `wrong_timeout` | partly | medium | needs app config change |

### J. Lifecycle

| Fault | Kernel-visible | Recipe risk | Note |
|---|---|---|---|
| `restart_storm` | **yes** — repeated process churn | **low** | container restart loop; a real production shape |
| `cold_start` | partly | medium | JIT warmup on a Java service |

### K. Cascading failure

| Fault | Kernel-visible | Recipe risk | Note |
|---|---|---|---|
| `retry_storm` | yes — connection count multiplies | medium | needs the load generator or a retrying client |

---

## What I recommend for v2

**Ten new families, all rated low recipe risk**, giving 22 families across 10 categories:

| Category | New families |
|---|---|
| F Concurrency | lock_contention, priority_inversion, deadlock |
| G Resource leak | fd_exhaustion, conn_pool_exhaustion |
| H Security | resource_abuse, data_exfiltration, fork_storm |
| I Configuration | dns_delay, nagle_delayed_ack |

**`dns_delay` was rated low risk and was nearly inert.** Its rule sat in the host's OUTPUT
chain, which catches lookups leaving the machine — and these applications almost never make
one, because they address each other by service name and Docker's embedded resolver answers
inside the container's namespace. Measured under load: p50 67.7 → 85.2 ms (noise), **11 packets
dropped in the entire probe**. Ten campaign runs of a fault that did nothing, and it passed
every smoke test because the check asked whether the rule existed rather than whether anything
happened.

Moved into the target's network namespace it becomes one of the better hard cases in the
catalogue:

| | p50 | p95 | wall |
|---|---|---|---|
| baseline | 71.9 ms | 201.7 ms | 914 ms |
| dropping 60% | 61.8 ms | 78.7 ms | **12,566 ms** |

Median fine, p95 fine, wall-clock **15x**. A few requests wait seconds on a retry while
everything below p95 sails through — so every summary statistic an operator would normally
reach for reports a healthy system. Same shape as `nagle_delayed_ack`, which is why both belong
here.

One implementation trap worth carrying: Docker DNATs `127.0.0.11:53` to a high port and `nat
OUTPUT` runs before `filter OUTPUT`, so a `--dport 53` rule inside a container matches nothing.
Match on the resolver's address.

Deliberately left out for now: `memory_leak`, `wrong_timeout`, `cold_start`, `retry_storm`.
All are medium-risk recipes, and on a campaign we cannot repeat, an untested recipe is a
worse risk than a missing family.

**They are parked, not dropped.** `future.md` records what each one is, why it waits, what
its recipe would need and what it would tell us — so picking one up later does not mean
redoing this thinking. `retry_storm` in particular is worth returning to: it is the case where
the symptom sits furthest from the cause, which is the hardest thing an agent can be asked to
do.

### What that costs

| | Value |
|---|---|
| New families | 10 |
| Runs each (5 repeats, both apps) | 10 |
| **New runs** | **~100** |
| Extra VM time | ~10 h |
| New campaign total | ~283 runs, ~30 h |

### What it changes about the pilot

This is the part worth insisting on. **Every new recipe must inject successfully in the pilot
before the campaign starts.** Ten untested recipes is exactly how a one-shot campaign gets
wasted.

So the pilot grows from 2 runs to **2 + one smoke run per new recipe** — about 12 runs, still
under two hours. Each smoke run has to show:

1. the fault actually took effect (`verification.json` says confirmed)
2. no events were discarded
3. the signal is visible in the trace at all

A recipe that fails its smoke run gets fixed or dropped **before** we spend 10 runs on it.

---

## Why these ones and not others

Two filters, both aimed at the same thing.

**Filter 1: can kernel traces see it?** Every family above leaves a mark we already record —
syscall returns, process creation, socket calls, scheduler events. Nothing here needs a
modality we do not collect.

**Filter 2: is it a look-alike?** The point of a blueprint is telling apart things that look
the same. These deliberately pair up with what we already have:

| New fault | Looks like | Why that is useful |
|---|---|---|
| `resource_abuse` | `noisy_neighbor` | both burn CPU; only the syscall profile differs |
| `fd_exhaustion` | `dependency_outage` | both stop serving; one fails at `open`, one never answers |
| `conn_pool_exhaustion` | `queue_backlog` | both are saturation of a shared resource |
| `deadlock` | `dependency_outage` | both go silent; one still holds threads |
| `dns_delay` | `slow_db` | both are "waiting on the network before work starts" |
| `nagle_delayed_ack` | healthy | the hardest case — nothing looks wrong anywhere |

That last row is the one Naser most wants: the agent alone should fail.

---

## Open question for you

Adding these means the campaign covers **10 categories** but analysis in phase 1 stays on
latency. That is the right order — collect once, analyse in stages — but it is worth being
explicit that most of these runs will sit unused until phase 2.

If VM time is the binding constraint rather than the second campaign, we could cut the
security group (3 families, ~30 runs) and still reach 9 categories.
