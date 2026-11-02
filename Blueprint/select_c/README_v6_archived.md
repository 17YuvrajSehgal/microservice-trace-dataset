# Blueprint selector C — rule out the mechanism, don't default to "slow"

You decide **which specialist blueprint takes this trace**, or that nothing is wrong. Output exactly
one `fault_type`: `svc_cpu_cap`, `noisy_neighbor`, `slow_db`, `svc_net`, `svc_mem_cap`, or `normal`.

## The trap that fools every naive selector (read this twice)

A fault on one request-path service makes that service **answer its callers slowly**, and the
callers pile up asleep on sockets waiting for it. The catch: **a CPU cap, a lossy network, and a
slow database ALL look the same at the aggregate level — a broad drop in activity.** If you stop at
"activity collapsed / answers are slow" you will call everything `slow_db`. That is wrong most of
the time.

**Three reasoning errors you must NOT make (each one has caused real misclassifications):**

1. **Do NOT reason from aggregate activity or total-CPU direction.** "sched_switch / wakeups /
   net_dev all fell, total CPU dropped from 7 cores to 2" is the SHARED symptom of a CPU cap, a
   lossy network, AND a slow dependency. A falling aggregate tells you a request-path service is
   stalled; it does NOT tell you why. It is not evidence for a dependency. Ignore the aggregate and
   go to the per-service checks below.

2. **A CPU cap LOWERS total CPU and leaves the CPUs IDLE — that is its signature, not evidence
   against it.** The intuition "a CPU fault means high, pegged CPU" is WRONG for a cap: the victim
   is *throttled down*, so it uses less CPU, and its idled callers use less too, so total CPU
   *falls* and cores sit *idle*. Idle CPUs + a falling total are exactly what a cap looks like. Do
   NOT conclude "CPUs are idle, so this is not a CPU problem and the service must be waiting on a
   dependency." That is the single most common error. Check Check 3.

3. **A degraded network collapses throughput too.** netem delay/loss makes a service's throughput
   fall just like a dependency slowdown. "activity down" is not `slow_db`. The thing that separates
   them is retransmission (Check 1). Run it before concluding anything.

**So: never conclude from the symptom. Identify the MECHANISM.** Run the checks below **in order**
and commit to the FIRST that clearly fires. `slow_db` is the *last* option — "slow answers" and
"activity collapse" are what a cap and a lossy path also produce, so db is only correct once the
others are ruled out.

## Setup

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/fault.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/base.txt
```
`WINDOW_START` = where the rate shifts and stays shifted; `BASE_START` = a quiet stretch OUTSIDE
that window (far from both edges). If `idx_summary` shows no sustained change, still run the checks
on a mid-recording slice; answer `normal` only if every check below is clearly absent.

## The checks — run in this order, commit at the first that fires

**Check 1 — svc_net (retransmissions).** Loss on a path shows as the SAME TCP segment sent twice.
**Cut network slices for this check** — the default slice keeps scheduling events only, and
`net_loss` on a sched-only slice always reads "no TCP segments" (a false ABSENT):
```bash
NETEV='sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/nf.txt "$NETEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/nb.txt "$NETEV"
python3 $TOOLS/net_loss.py $WORK/nf.txt 10
python3 $TOOLS/net_loss.py $WORK/nb.txt 10
```
FIRES if any container's flows show retransmissions **clearly above the baseline slice**.
Retransmission is the definitive network signature: packet loss **cannot** happen without it, and a
merely-slow dependency produces **zero**. So even a modest per-flow retransmission rate on one
service's flows, against a ~0% baseline, means the network path — commit to it, do not fall through
to `slow_db`. → **`svc_net`**.

If retransmission is low, do NOT conclude anything yet — a delay-only impairment is decided in
Check 5, **after** the CPU checks have run. (A CPU-capped service also answers all its callers
slowly; only once CPU starvation is ruled out does "slow on all flows" mean the network path.)

**Check 2 — svc_mem_cap (reclaim).** A memory limit makes the kernel reclaim over and over.
Cut a memory slice (the default slice has no memory events):
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/mf.txt 'mm_vmscan|sched_process_exit'
grep -c -E "mm_vmscan|memcg|reclaim" $WORK/mf.txt
```
FIRES if memcg-reclaim events are present (and a process re-reads heavily / high `D`). If the trace
carries no memory events at all, this fault is not visible here — ABSENT. → **`svc_mem_cap`**.

**Check 3 — svc_cpu_cap (one service pinned at a flat sub-core CPU ceiling).** THE check naive
selectors skip. A quota caps the victim's CPU at a **flat, sub-core plateau** — this is the
confident signal, more reliable than runnable-wait. Compute each busy container's CPU use (cores)
during the window and find the ONE pinned at a flat LOW fraction of a core:
```bash
python3 $TOOLS/cpu_hogs.py    $WORK/fault.txt 10              # per-container CPU; is the host mostly IDLE?
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10            # the victim also has high RUNNABLE wait
# confirm the suspect's per-period ceiling against the quiet baseline. Pass the victim's
# PROCESS NAME or its PID from sched_budget's pid column - NEVER a pid_ns id
# (4026... numbers are namespaces, not pids; the tool will reject them):
python3 $TOOLS/cpu_ceiling.py $WORK/fault.txt <victim_name_or_pid> 100 $WORK/base.txt
```
FIRES if **one service's CPU use sits at a flat, low, sub-core value** (e.g. pinned near ~0.2 or
~0.5 of a core, steady across the window) while the host CPUs are largely **IDLE** and that service
has high **runnable wait** — and `cpu_ceiling` shows a per-period ceiling below the period that
collapsed from its baseline. A service held at a fixed fraction of a core while CPUs sit idle = a
quota. → **`svc_cpu_cap`**.

Do NOT stop at "total CPU fell" or get distracted by which cohort of processes came and went —
**find the ONE service pinned at a flat fraction of a core.** That plateau is the cap; the rest of
the collapse is the cascade behind it.

**Subtle caps (quota near the victim's natural use) still count — do not demand a dramatic
plateau.** A 0.5-core cap on a service that wanted ~0.6 cores shows a modest collapse and a
wobblier ceiling. Commit on the CONJUNCTION, not on how crisp the plateau looks: the same service's
per-period CPU is *lower than its own baseline* AND bounded below a sub-core value, it carries
runnable waits the baseline lacks, and the CPUs are idle while it waits. If those three agree,
that is `svc_cpu_cap` even when the ceiling is not razor-flat; do not fall back to "normal"/"other"
just because the signal is moderate.

**Check 4 — noisy_neighbor (CPU stolen).** Same runnable-wait, but the CPUs are **BUSY**.
```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault.txt 10     # who holds the CPU; compare to base.txt
```
FIRES if the top runnable-waiter waits while the CPUs are **BUSY** and a process/group absent in
baseline now holds a large share, arriving with the window. → **`noisy_neighbor`**.

**Check 5 — the slow-answer split: svc_net (delay) vs slow_db.** ONLY if 1–4 did not fire — i.e.
no retransmission, no reclaim, and the affected service is NOT CPU-starved (it sleeps on sockets:
high `S`, low runnable wait, little CPU). Now the question is WHO it is waiting for:
```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10    # confirm: S-dominated, runnable wait low
python3 $TOOLS/sock_lag.py    $WORK/fault.txt 10 all # per-fd request-to-answer gaps vs baseline
```
Read the per-fd gaps of the affected service against the baseline slice:
- gaps jumped ONLY on the connections **to one dependency** (e.g. a DB pool — a few fds to one
  peer), the service's other flows stay fast → that dependency is slow → **`slow_db`**.
- gaps jumped on **ALL or most of the service's flows/peers at once** (its callers' requests AND
  its own calls out) → the service's own network path is impaired (delay without loss) →
  **`svc_net`**, marked inferred. A database cannot slow down traffic that never touches it.

If none fired → **`normal`**.

## The one rule that decides cpu_cap vs slow_db (get this right)

Both make a service answer slowly. The difference is **why the service itself is slow**, read from
its OWN `sched_budget` row:

- **dominant RUNNABLE wait + idle CPUs** → the service is *denied CPU* → **`svc_cpu_cap`**
  (even though its slowness also makes callers wait — that cascade is a consequence, not the cause).
- **dominant SLEEP (`S`) on sockets, low runnable wait, little CPU** → the service is *waiting on its
  own downstream* → **`slow_db`**.

Rank candidates by the **runnable `wait`** column for Checks 3–4 (the capped service tops it); the
sleeping cascade victims top the `S` column and are NOT the cause. Never answer `slow_db` or `other`
without having run Checks 1 and 3 — "slow answers" alone is not enough to tell these apart.

## Output

Commit to exactly one `fault_type`. In the evidence, name which check fired and its number
(retransmission rate, runnable-wait rise + idle%, reclaim count, or sleep-on-socket gap). Do not
output `other`. Answer `normal` only when all five checks are clearly absent.
