# Future work — parked, not dropped

Things we decided **not** to do now, with enough detail to pick them up later without
redoing the thinking. Nothing here is abandoned; each entry says why it waits and what it
would need.

---

## Fault families deferred from the v2 collection

Four families were cut from the v2 campaign on 4 Sept 2026. **All four are good ideas.** They
were cut for one reason: on a campaign we cannot repeat, a recipe that has never been tested
is a worse risk than a missing family. Each of these needs more than a few lines of shell, so
each carries a real chance of producing runs that do not inject properly.

If a later campaign has room to pilot them properly, they should go back in.

### 1. `memory_leak` — slow growth, not a step change

**What it is.** A service that leaks memory steadily until it starts reclaiming, and
eventually hits its limit.

**Why it is worth having.** Every fault in our dataset is a **step change** — it is off, then
it is on. Real incidents often creep. A leak looks completely healthy for most of the window
and only turns bad near the end. That is a genuinely different detection problem, and we have
no example of it.

**Why deferred.** Needs a leaking sidecar or a patched service, and needs a long enough run to
show the trend. Our windows are 60 s baseline plus 120 s injection, which is probably too
short for a leak to be distinguishable from noise. Getting it right likely means a longer run
shape, which changes the campaign structure.

**What it would need.**
- a container that allocates and holds memory at a controlled rate
- a longer run (10+ minutes) so the trend is visible
- memory tracepoints on, so reclaim can be seen rising rather than inferred

**What it would tell us.** Whether a blueprint can catch something *before* it becomes an
incident — which is a different and more valuable claim than naming a fault after the fact.

### 2. `wrong_timeout` — a mistake, not a failure

**What it is.** A client timeout set too low (or too high) for the dependency it calls.
Nothing is broken. The system is configured wrong.

**Why it is worth having.** Configuration mistakes are a large share of real incidents and we
have none. It also has a nasty shape: a too-short timeout produces retries and errors that
look like the *dependency* is failing, when the dependency is fine.

**Why deferred.** Needs an application-level config change per service, which is different for
Sock Shop (Node, Go) and Train Ticket (Java/Spring). That is per-app work, and per-app work is
where identical matrices break down.

**What it would need.**
- a way to set client timeouts per service, the same way on both applications
- ideally an environment variable rather than a code change

**What it would tell us.** Whether a blueprint can point at the *caller's configuration*
rather than at the callee, which is where the obvious evidence points.

### 3. `cold_start` — the warm-up period

**What it is.** A freshly started service is slow while the JIT warms up, caches fill and
connection pools open.

**Why it is worth having.** It is a real and very common source of latency, and it is
**temporary** — which means a blueprint should say "wait, this will pass" rather than "fix
this". None of our current blueprints can say that.

**Why deferred.** Only partly visible in kernel traces. The JIT compiling is CPU work that
looks like ordinary CPU work. Telling warm-up apart from a genuine CPU problem may need the
application layer, and phase 1 is kernel-only.

**What it would need.**
- restart a service mid-run and trace the recovery
- probably spans or metrics to confirm the latency really did settle

**What it would tell us.** Whether the system can recognise a *self-healing* problem. That is
a different kind of verdict and worth having in the taxonomy.

### 4. `retry_storm` — the failure that amplifies itself

**What it is.** A small failure causes clients to retry, retries multiply the load, and the
extra load makes the original failure worse.

**Why it is worth having.** This is the classic cascading failure, and it is the one where
**the symptom is furthest from the cause**. By the time anyone looks, the whole system is
saturated and the original trigger is invisible. That is the hardest possible case for an
agent, and exactly the kind Naser wants.

**Why deferred.** Needs either a retrying client or changes to the load generator, plus
careful tuning — too weak and nothing happens, too strong and the whole stack falls over and
the run is useless. Both failure modes waste runs.

**What it would need.**
- a load generator mode that retries on failure, with a configurable retry count
- a mild trigger fault to start the cascade
- calibration, because the useful window between "no effect" and "everything dies" is narrow

**What it would tell us.** Whether a blueprint can walk *backwards* from a saturated system to
the small thing that started it. If it can, that is the strongest result the project could
produce.

---

## Other parked items

Shorter notes on things deferred elsewhere, kept here so they are in one place.

| Item | Why parked | Where it came from |
|---|---|---|
| **A third application** | Biggest thing for the paper's strength — two apps cannot tell us whether a signature belongs to the fault or to our VM shape. Also the most expensive | COLLECTION-PLAN.md |
| **eBPF or perf alongside LTTng** | Would show blueprints port across collectors, which the thesis will want to claim | 2 Sept meeting |
| **A different machine shape** | Some of our numbers already invert between apps; a second shape would show how much is hardware | COLLECTION-PLAN.md |
| **`clock_skew` fault** | Interesting because it breaks distributed tracing itself, but risky — it could corrupt the timestamps the whole run depends on | FAULT-CATEGORIES-V2.md |
| **Compound faults** | Two faults at once. We have zero, and Naser asked for combined causes. Needs a wrapper that runs two recipes together | COLLECTION-V2-SPEC.md |
| **Logs, metrics and spans as analysis inputs** | Explicitly parked by the 2 Sept meeting — kernel first | todo-points 02-09 |
| **Mahsa's GitHub-mining agent** | An agent that reads other RCA tools' repos and turns their functions into blueprints. Interesting as its own project | todo-points 02-09 |

---

## Findings we have not chased

| Lead | Status |
|---|---|
| Memory faults called noisy neighbours (3 wrong answers) | Two workarounds died the same way — block latency (F18) and interrupt time (F20) each worked on one app and failed on the other. Only route left is collecting memory tracepoints, which v2 does |
| Kernel-level lock contention | We can only see user-level locks via `futex`. Whether `lock_*` tracepoints exist on our VM is **unverified** — one `lttng list --kernel` answers it |
| CPU frequency scaling, priority, NUMA | Never tried. We record no `power_*` events, so frequency is invisible today |
