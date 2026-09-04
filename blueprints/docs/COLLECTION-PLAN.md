# Do we need new data? Yes — three things, and a few cheap extras

Written 4 Sept 2026, from the 2 Sept meeting plan and what our 109 runs already show.

---

## Short answer

**Three things need new collection.** Everything else we already have.

| # | What | Why it cannot wait |
|---|---|---|
| 1 | Memory events turned on | The only route left to our 3 wrong answers |
| 2 | A lock contention program | Naser asked for it. We have the control but no example |
| 3 | Two "agent will fail" programs | The demo needs cases where a blueprint clearly wins |

Everything else is worth adding **while the machine is up**, but is not blocking.

---

## Before anything: one command

On the new VM, before planning around locks:

```bash
lttng list --kernel | grep -i lock
```

This tells us whether kernel lock tracepoints exist. Naser asked for **kernel** lock
contention. Today we can only see **user-level** locks, through `futex`. If those tracepoints
are missing, we either accept user-level locks or rebuild the kernel — and that changes what
B1 is. One command, do it first.

Do the same for `power_*` (CPU frequency) while you are there.

---

## 1. Memory events — the only must-have re-collection

**The problem.** Our rule engine gets 3 answers wrong. All 3 are the same: a memory fault
called a noisy neighbour. Memory stress runs a program that eats a CPU core, so it looks like
CPU theft.

**Why we cannot fix it with what we have.** Our traces carry **no memory events at all**. They
are switched off on purpose because they are the biggest, most expensive class. We tried to
work around it twice:

| Attempt | Result |
|---|---|
| Disk latency (F18) | Worked on one app, failed on the other |
| Interrupt time (F20) | Worked on one app, failed on the other |

Both died the same way. There is no third workaround left. We have to record the memory layer.

**What to collect.** Set `KERNEL_MEM=1` and re-run these families:

| Family | Runs per app | Why |
|---|---|---|
| `anomaly_mem` | 3 | the fault we cannot name |
| `noisy_neighbor` | 3 | the one it gets confused with |
| `svc_mem_cap` | 3 | the container version, and we only have 2 |
| `normal` | 3 | the healthy control |

**12 runs per app, 24 for both.**

**Cost:** memory events push a run from 2–3 GB to roughly 8 GB. So about **200 GB** for both
apps. Plan the disk for that.

Start with one app. If the memory layer does not separate the two faults there, stop — do not
spend the second app on it.

---

## 2. Lock contention — we have half of it

`futex` is a system call, and we record every system call. So lock waits are already in all
109 runs, and we already checked them:

**Good:** total lock wait moves for **nothing** we inject (biggest move 1.38x and 1.11x). That
is the negative control, done, before the blueprint exists.

**Missing:** we have never injected lock contention, so there is **no positive example**. We
know what "no lock problem" looks like. We do not know what "lock problem" looks like.

**What to collect.** A small program with a contended lock, traced 5–10 times. Plus its
look-alike, because that is what proves the blueprint separates them:

| Program | What it does |
|---|---|
| Real contention | many threads fight over one short-held lock |
| Look-alike: idle parking | a thread pool waiting for work |

That second one matters. On our first look, total lock wait was **408 seconds per second** of
real time — Java thread pools parked waiting for work, not contention. Idle parking drowns
the signal. The blueprint must key on the **shape**: contention is many short waits, parking
is a few long ones.

---

## 3. The two cases where the agent should fail

Naser was clear: a blueprint has to earn its place on **hard** problems. These two are hard
because **nothing looks busy**.

### Priority inversion

A low-priority thread holds a lock. A high-priority thread waits for it. A medium-priority
thread hogs the CPU, so the lock holder never gets to run and never releases.

Everything stalls. CPU is not saturated. Disk is idle. Network is fine. An agent has no reason
to guess this. It is a famous bug and about 30 lines of code.

### Nagle plus delayed ACK

Small writes without `TCP_NODELAY` hit a fixed ~40 ms stall. CPU idle, disk idle, **no packets
lost**, nothing retransmitted. Every signal we have says the system is healthy.

Also famous, also easy to write.

**Both fit the demo exactly:** the agent alone fails, the blueprint wins. That is the story
Naser asked for.

---

## Worth adding while the machine is up

These do not justify a VM on their own. They are cheap once one is running.

### 4. Compound faults — we have zero

Naser asked for **combined** causes, not just single ones. We have **no runs with two faults at
once**. All 12 recipes inject one thing.

Every look-alike pair we know about is a candidate:

| Pair | Why it is interesting |
|---|---|
| CPU cap **while** holding a lock | measured: a throttled thread freezes for its whole 100 ms slice, and everything waiting on it inherits that |
| Memory cap **plus** network load | a capped container already drops packets harder than a real network fault |
| Disk fault **plus** memory pressure | both raise interrupt time, and we only know their order apart |
| Slow database **plus** CPU contention | does the database blueprint still fire when the caller is also starved? |

3 runs each, 12 runs per app. This is the honest test of whether one blueprint can fire while
another is also true.

### 5. Top up the thin families

Some thresholds rest on very little:

| Family | Runs we have (both apps) | Comment |
|---|---|---|
| `svc_mem_cap` | **4** | thinnest in the whole library, and it now has a blueprint |
| `anomaly_disk` | 4 | has a blueprint |
| `queue_backlog` | 2 | proved unbuildable, low priority |

Take `svc_mem_cap` and `anomaly_disk` to 6 per app.

### 6. More healthy runs, at different loads

We have 8 healthy runs. They set the ceiling every threshold has to clear — for example the
interrupt bar sits at 2.5 only because the busiest healthy run reached 1.81.

More healthy runs at **different load levels** is the cheapest way to find out whether our
thresholds are safe or lucky.

### 7. Intensity calibration — already owed

From the project notes: the VM still owes intensity calibration, especially the noisy
neighbour case where "KPIs barely move". Also owed: the per-container network recipe and the
injection verification script. Worth clearing while the machine exists.

---

## Outside latency — useful, not urgent

### A third application

Our strongest method rule came from being burned: **a signal does not enter a blueprint until
it is checked on both applications.** Two signals looked perfect on one app and died on the
other.

But two apps still cannot tell us whether a signature is a property of the **fault** or of
**containerised Java and Node on one VM shape**. A third, different application would.

This is the single biggest thing we could do for the paper's strength. It is also the most
expensive. Not now, but worth naming.

### Different machine shape

All our numbers come from one VM type. Absolute values already invert between our two apps
(interrupt seconds). A second machine shape would show how much of that is hardware.

### eBPF or perf side by side

The meeting said eBPF and perf are options later, since they all write the same format. One
run collected with both LTTng and eBPF would tell us whether our blueprints port across
collectors, which is a claim the thesis will want.

---

## What the new VM needs

The fast path already exists — do not rediscover last time's bugs:

```bash
git clone --recursive <repo>
microservice-lttng-data-collection-scripts/vm_bootstrap.sh   # LTTng, Docker, images, stack
run_gate.sh gate01                                           # collect + load + metrics + audit
```

Gotchas and fixes: `microservice-lttng-data-collection-scripts/TROUBLESHOOTING.md`

| Requirement | Value |
|---|---|
| OS | Ubuntu 24.04 |
| Tools | LTTng 2.15, Babeltrace2, Docker 27+ |
| Machine | same type as before, or note the change — absolute numbers depend on it |
| Disk | **plan for 8 GB per run** if memory events are on, not 2–3 GB |

One warning about the memory runs: `--cpus=0` and `-m 0` are silent no-ops in the Docker API,
and memory limits cannot be cleared once set. Verify restores against `/sys/fs/cgroup/*`, not
`docker inspect`.

---

## Suggested order

| Order | What | Runs | Blocks what |
|---|---|---|---|
| 1 | `lttng list --kernel` check | 0 | decides what B1 is |
| 2 | Lock contention + idle-parking programs | ~20 | B1 |
| 3 | Priority inversion, Nagle/delayed-ACK programs | ~20 | the demo |
| 4 | Memory events on, one app | 12 | our 3 wrong answers |
| 5 | Memory events, second app | 12 | only if step 4 worked |
| 6 | Compound faults | 12–24 | Naser's combined causes |
| 7 | Top-ups and healthy runs | ~20 | threshold confidence |

**Steps 1–3 need no microservice deployment at all.** They are small programs on a plain VM,
which means a much cheaper machine and a much faster loop. Only steps 4–7 need the full Sock
Shop or Train Ticket stack.

That split is worth knowing before choosing machine types: you may want **two** machines — a
small one for the programs, and the usual one for the microservice runs.
