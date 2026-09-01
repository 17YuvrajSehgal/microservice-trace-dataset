# Blueprint backlog — which anomalies to write, and in what order

Written 2026-08-29, after E1 batch 1. Ordering is driven by measurement (finding F2), not by
coverage counting.

---

## The principle: the next blueprints are the fix for the ones we have

E1 measured a **42% false-positive rate** on runs neither existing blueprint should claim.
Every false fire points at a blueprint that does not exist yet:

| False fire | What it was | What it was called | The missing blueprint |
|---|---|---|---|
| `dependency_outage` ×2 | a hung dependency | `db_latency` @0.85 | **frozen-dependency** |
| `svc_net` ×2 | added network delay | `db_latency` @0.85 | **service-network-path** |
| `normal` burst ×1 | nothing wrong | `noisy_neighbor` @0.80 | **healthy-baseline** (a verdict, not a fault) |
| `anomaly_cpu` ×3 | host CPU saturation | quiet — but only by luck | **host-cpu-saturation** |
| `svc_cpu_cap` ×2 | cgroup throttle | quiet — but only by luck | **service-cpu-throttle** |

A two-blueprint library forces every incident into one of two answers. Building the siblings
is not "more coverage" — it is what makes the existing two safe.

---

## What we have data for

All 110 labelled runs, both applications. Kernel traces exist for every run.

| Family | Sock Shop | Train Ticket | Kernel-only viable? |
|---|---|---|---|
| `noisy_neighbor` | 5 | 5 | yes — **done** |
| `slow_db` | 7 | 7 | yes — **done** |
| `anomaly_cpu` | 3 | 3 | yes |
| `svc_cpu_cap` | 5 | 5 | yes |
| `svc_net` | 3 | 3 | yes |
| `dependency_outage` | 3 | 3 | yes |
| `anomaly_mem` | 7 | 3 | yes |
| `anomaly_disk` | 3 | 3 | yes |
| `queue_backlog` | 3 | **0** | yes — SS only |
| `anomaly_net` | 3 | 3 | partly |
| `svc_mem_cap` | 3 | 3 | partly — OOM shows in logs |
| `error_storm` | 5 | 5 | **no** — logs |
| `normal` | 7 | 6 | negative control |

---

## Tier A — required to make the current two blueprints safe

Build these next. Each one closes a measured false fire.

### A1. `host-cpu-saturation` — the host itself is out of CPU  ✅ BUILT 2026-08-29
- **Family:** `anomaly_cpu` · SS 3, TT 3
- **Why first:** measured **36.97–52.54×** runqueue delay on 12 processes — seven times the
  7.12× of the co-tenant fault the CPU blueprint was written from. It satisfies every
  positive condition of `cpu-contention` and stayed quiet only because its socket waits
  tripped an unrelated veto.
- **The separating question:** is there headroom? Co-tenant contention leaves the host
  *unsaturated* (5.31 → 7.96 cores of N). Saturation does not. Both are computable from
  `sched_switch` on-CPU time — `oncpu_share.py` already measures it.
- **Sibling of:** `cpu-contention-co-tenant`, `service-cpu-throttle`

### A2. `service-cpu-throttle` — one service is capped by its cgroup  ✅ BUILT 2026-08-29
- **Family:** `svc_cpu_cap` · SS 5, TT 5
- **Why:** measured 13.54–15.70× runqueue on 5–6 processes. Same collision (finding F1).
  Published precedent: Gelle/Ezzati-Jivan/Dagenais 2021 demonstrate a cgroup limit producing
  threads "waiting on CPU" — the exact signature.
- **The separating question:** *breadth and direction.* A cap delays the capped service's
  threads while that service **loses** CPU; a co-tenant delays many unrelated services while
  a newcomer **gains** CPU. `oncpu_share.py` reports both (`cores_gained`, `biggest_loser`).
- **Note:** the `subtle` runs are the sharp test — F1 predicts a mild cap fires the CPU
  blueprint outright. Queued in E1 batch 2.
- **Sibling of:** A1, `cpu-contention-co-tenant`

### A3. `service-network-path` — the network path to a service is degraded  ✅ BUILT 2026-08-30 as `network-path-degradation`
- **Family:** `svc_net` · SS 3, TT 3
- **Why:** measured `epoll_pwait` at **140–175×** — the *strongest* socket-block signal in
  the whole sweep, stronger than the real datastore fault at 36.8×. Fired `datastore-wait`
  confidently on both runs.
- **The separating question:** blocked **on what**. Needs the socket peer, not just the
  syscall duration. That is a new capability: peer/endpoint attribution from
  `syscall_entry_connect` / `sendto` / socket fd tracking.
- **Sibling of:** `db-latency-dependency-wait`, A4

### A4. `frozen-dependency` — a downstream dependency hangs rather than errors  ❌ NOT BUILDABLE from kernel data (F11-F15)
- **Family:** `dependency_outage` · SS 3, TT 3
- **Why:** measured `poll` at **84–89×**, fired `datastore-wait` confidently. Semantically the
  nearest miss of all: it *is* a dependency wait, just not on a datastore.
- **The separating question:** does the call ever complete? A slow datastore returns slowly;
  a frozen dependency does not return — waits terminate on timeout, and the caller's request
  fails. Distinguishable in kernel by wait-duration distribution shape (clustered at the
  timeout value) rather than magnitude.
- **Sibling of:** A3, `db-latency-dependency-wait`

### A5. `healthy-baseline` — nothing is wrong
- **Family:** `normal` · SS 7, TT 6
- **Why:** `normal_none_burst_r1` was diagnosed as a host noisy-neighbour at 0.80 confidence.
  Two of three no-fault runs sat at or above the CPU blueprint's firing threshold.
- **Not a fault blueprint.** It is the *verdict* the library currently cannot reach. Needs a
  workload-shift discriminator: a burst raises runqueue delay and throughput together,
  whereas contention raises delay while throughput flattens or falls.
- **This is the highest-severity item in the list** — a false alarm on a healthy system costs
  more credibility than a missed diagnosis.

---

## Tier B — new ground, kernel-viable, no known collision yet

Worth building once Tier A closes the false fires.

### B1. `host-memory-pressure` — the host is reclaiming
- **Family:** `anomaly_mem` · SS 7 (most runs of any family), TT 3
- Kernel-visible via reclaim and page-fault activity. Distinct mechanism from anything built.

### B2. `host-disk-saturation` — the storage device is the bottleneck  ✅ BUILT 2026-09-01
- **Family:** `anomaly_disk` · SS 3, TT 3
- Block-layer latency; expected to look like "blocked" but on `block_rq_*`, not sockets.
  Likely another `datastore-wait` impostor — worth testing before building.

### B3. `async-queue-backlog` — work queues up silently  ❌ NOT BUILDABLE from kernel data (F19)
- **Family:** `queue_backlog` · SS 3, **TT 0**
- The "silent failure" case: our catalogue records it as kernel-only by construction, with no
  metric or log signal. Strongest showcase of the kernel modality — but **Sock-Shop-only**,
  so it cannot be cross-app validated. Build it, and state that limit.

---

## Tier C — needs modalities beyond kernel (phase 2+)

Listed so the taxonomy is complete, not scheduled now.

| Blueprint | Family | Blocked on |
|---|---|---|
| `app-error-burst` | `error_storm` (SS 5, TT 5) | logs — the signal is 5xx rate, not kernel |
| `service-memory-cap` | `svc_mem_cap` (SS 3, TT 3) | logs — OOM-kill is the tell |
| `host-network-degradation` | `anomaly_net` (SS 3, TT 3) | traces — kernel sees the wait, not the loss |

---

## Status

**`async-queue-backlog` attempted and NOT buildable (F19).** It is indistinguishable from
`dependency_outage`: both pause a container in the same async chain, so both kill the AMQP
conversation, and the flow view cannot say which end died. Worse, the same shape appears in
seven of thirteen families on Sock Shop — "the queue went quiet" means "the system slowed
down", not "the consumer is paused".

This is the second `docker pause` fault that cannot be identified, for the reason found in
F11/F12: a frozen container produces *absence*, and absence has too many causes. The library
correctly declines all `queue_backlog` runs, so it is a coverage gap rather than a source of
wrong answers.

Worth recording against the pre-registration: `fault_catalog.md` calls this the hardest
detection case and names **kernel** as the winning modality. **We could not deliver it.** The
catalogue's reasoning needs per-cgroup attribution; our trace has shared process names and no
memory events.


**`host-disk-saturation` built 2026-09-01.** Sixth blueprint. Measured across 58 runs covering
ALL 13 families on both applications from the start — the F17 lesson applied rather than
learned again.

The deciding signal is **who arrived on the disk**: a process gaining thousands of requests
per second it was not making before. Disk flooding 4724–6944 req/s against a 1170 ceiling for
every other family — a 4.0× gap that holds on both apps, which only packet loss had managed
before.

Two retractions carried. The catalogue predicted *"DB threads in D-state waits"*; device
latency actually stays **flat or falls** under disk flooding (0.54–1.12×), because the
stressor writes large sequential blocks that complete quickly. Queue depth falls too. Both are
recorded as things not to use.

Unexpected lead: device latency rises **10.7–14.5×** under *memory* pressure, with queue depth
roughly doubling. F10 had written `anomaly_mem` off as unresolvable without `mm_*` tracepoints
— the block layer sees the consequence even though the memory layer is untraced. Sock Shop
only, so a lead rather than a rule, but it is the first crack in the three remaining
`anomaly_mem` wrong answers.


**Network blueprint built 2026-08-30 as `network-path-degradation`** — one blueprint, not the
two planned. Breadth separates host-wide from single-service impairment on Sock Shop (7–12
interfaces against 1–3) and reverses on Train Ticket (0–1 against 1–2), so splitting them
would assert a distinction that holds on only one system. Scope is reported as evidence.

The deciding signal is **TCP retransmission**, not latency. Network faults are the only family
in the catalogue that drop packets, and a dropped segment must be re-sent. Measured across 40
runs: network 18.5–60.7%, every other family ≤7.1%, baseline exactly 0.00% in all 40.

**A4 `frozen-dependency` is not buildable from kernel data.** Five constructions measured and
all negative — on-CPU time, threads that stop being scheduled, threads that stop being woken,
endpoint latency, and packet loss. A paused container does not drop packets or stop being
woken; it stops answering. `fault_catalog.md` pre-registers traces and logs for it. Revisit in
phase 2.


**CPU cluster (A1 + A2) built 2026-08-29**, together with a v7 revision of
`cpu-contention-co-tenant`. All three were authored from one 17-run measurement (finding
F3), because none is separable on its own. The deciding signal turned out **not** to be
runqueue delay — that was demoted to corroboration in all three — but host CPU utilisation,
which splits the four families with no overlap.

Still owed for this cluster: rewire `blueprint_decide.py` onto the new signals, then re-run
E1 to see whether the 42% false-positive rate falls.

## Order of work

1. **A5 `healthy-baseline`** — highest severity, and it needs no new fault data.
2. **A1 + A2 together** — one CPU cluster. Building them separately repeats the F1 mistake;
   the discriminators only exist relative to each other.
3. **A3 + A4 together** — one wait cluster, same reason.
4. Re-run E1 over the whole negative class with the expanded library. The number that matters
   is whether the false-positive rate falls from 42%, not whether each new blueprint scores
   well on its own family.
5. Tier B.

**Rule carried over:** no discriminator enters a blueprint before it is measured on our own
data, and each new blueprint must be checked against the *other* families, not only its own.
That is the mistake E1 exists to stop us repeating.
