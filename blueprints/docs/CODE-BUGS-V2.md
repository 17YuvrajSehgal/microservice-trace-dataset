# Injecting real code bugs, not just infrastructure faults

Proposed 4 Sept 2026. Yuvraj: *"we can inject some coding issues that will lead to different
faults, contentions, locks or other problems."*

---

## Why this is the strongest idea on the list

Every fault we inject today is **external to the code**. We throttle a cgroup, add netem
delay, pause a container, run a stressor. The application is innocent; the environment is
made hostile.

Real incidents are usually the opposite. The environment is fine and **the code is wrong**.

This is also the first question a reviewer asks about any fault-injection dataset: *does an
injected fault look like a real bug?* Right now our honest answer is "we do not know". With
code bugs in the dataset, we can answer it with measurements.

---

## Why it is feasible — we already do the hard part

We do not deploy stock images. We **build two Sock Shop services from our own forks**:

```
git clone -b otel-instrumentation https://github.com/17YuvrajSehgal/catalogue.git
docker build -f catalogue/docker/catalogue/Dockerfile -t catalogue-otel:phase0 catalogue/

git clone -b otel-instrumentation https://github.com/17YuvrajSehgal/front-end.git
docker build -t frontend-otel:phase0 front-end/
```

A bug is **one more branch and one more image tag**. The pipeline that builds a patched
service already exists and is proven — we used it to add OpenTelemetry.

That matters because it turns a research idea into a small amount of ordinary work, instead of
new infrastructure.

| Service | Language | Fork exists | Bugs we can write |
|---|---|---|---|
| `catalogue` | Go | yes | locks, N+1 queries, leaks |
| `front-end` | Node | yes | event-loop blocking, N+1 calls, unbounded cache |
| Train Ticket services | Java | fork exists | synchronized methods, pool exhaustion |

---

## The experiment that makes this publishable

Not "we injected bugs". This:

> **The same symptom, once from the environment and once from the code. Can a blueprint tell
> them apart — and if not, does it say so honestly?**

For each pair below, we already have the left column. The right column is new.

| Symptom | Environment cause (have) | Code cause (new) | The question |
|---|---|---|---|
| Threads waiting on a lock | `lock_contention` stressor | **lock held across a database call** | Same kernel signature, completely different fix. Can we separate them? |
| The database path is slow | `slow_db` (toxiproxy delay) | **N+1 query in a loop** | One is the database's fault, one is the caller's |
| One service is slow, host is fine | `svc_cpu_cap` (quota) | **blocking the Node event loop** | A quota you can raise, versus code you must change |
| Runs out of file descriptors | `fd_exhaustion` (synthetic) | **connection never closed** | Same end state, very different onset |
| Hits the memory limit | `svc_mem_cap` (cgroup) | **unbounded cache growth** | A limit set too low, versus a genuine leak |

**Both answers are results.** If the kernel signatures are identical, the honest verdict is
*"threads are serialised on a lock — I cannot tell you from kernel data whether that is
contention or a coding mistake"*. That is a useful, truthful limit, and it is exactly the kind
of thing Naser said he wants written down.

---

## The bugs, concretely

Each is a small patch. The ones marked **first five** are what I would build.

### Go — `catalogue`

**1. Lock held across I/O** ← *first five*
```go
mu.Lock()
rows, err := db.Query(...)   // the lock is held for the whole database round trip
mu.Unlock()
```
Every request serialises behind one lock. This is the single most common real concurrency bug
in service code, and it is the honest version of the lock-contention case Naser asked for —
caused by code rather than a synthetic stressor.

**2. N+1 query** ← *first five*
One query for the list, then one more query per row inside the loop. Database work multiplies
with result size. Looks like a slow database; the database is fine.

**3. Goroutine leak**
A goroutine started per request that blocks forever. Memory and thread count creep.

**4. Rows never closed**
Missing `defer rows.Close()`. Connections leak until the pool is exhausted.

### Node — `front-end`

**5. Blocking the event loop** ← *first five*
A synchronous CPU-heavy call inside a request handler. Node has one thread, so **the whole
service stops** — including requests that have nothing to do with the slow path. Nothing else
in our dataset produces that shape.

**6. Serial calls instead of parallel** ← *first five*
`await` in a loop where `Promise.all` was meant. Latency grows linearly with the number of
items. Looks like a slow dependency.

**7. Unbounded cache** ← *first five*
Cache keyed on something unbounded, never evicted. Memory grows until the container limit is
hit — the code version of `svc_mem_cap`, and it also gives us the `memory_leak` shape parked
in `future.md`.

### Java — Train Ticket

**8. `synchronized` on a hot method**
Serialises every request through one monitor.

**9. Thread pool starvation**
A blocking call made from inside a small pool; the pool fills and everything queues.

---

## Ground truth — better than our infrastructure faults

A code bug has **sharper** ground truth than an injected fault, because the cause is a line of
code:

```json
{
  "fault": "code_lock_held_across_io",
  "kind": "code_defect",
  "service": "catalogue",
  "repo": "17YuvrajSehgal/catalogue",
  "branch": "bug/lock-across-io",
  "commit": "<sha>",
  "patch": "catalogue.go +142,-3",
  "mechanism": "mutex held for the duration of a database round trip",
  "expected_symptom": "requests serialise; wait time grows with concurrency",
  "correct_fix": "release the lock before the query",
  "pairs_with": "lock_contention"
}
```

`correct_fix` is new and worth having. It lets us ask a harder question than "what broke": **is
the recommended action right?** No infrastructure fault gives us that, because "raise the
quota" is the only possible answer.

---

## Cost and risk

| | Value |
|---|---|
| Bugs to build first | 5 |
| Runs each (5 repeats, one app) | 5 |
| **New runs** | **~25** |
| Extra VM time | ~2.5 h |
| Extra work | 5 branches, 5 image builds |

**The real risk is not the runs, it is the builds.** A patched image that fails to start
wastes a slot, and a bug tuned too weakly produces a run where nothing happens.

Mitigation, same as for the other new families: **every bug branch gets a smoke run in the
pilot.** It must build, start, serve traffic, and show its symptom before it earns campaign
runs.

Second risk worth naming: a code bug changes the service binary, so its **baseline is not
identical to the stock service**. Each bug run should be paired with a healthy run of the
*same patched image with the bug disabled by a flag*, so the comparison isolates the defect
rather than the rebuild. That is one extra healthy run per bug, and it is what makes the
result trustworthy.

---

## Recommendation

Build the **first five**: lock-across-IO, N+1 query, event-loop block, serial-instead-of-
parallel, unbounded cache.

They cover three languages' worth of realistic defects, they pair with five faults we already
have, and together they answer the reviewer question our dataset currently cannot.

Add the Java ones later if Train Ticket's build loop proves quick.
