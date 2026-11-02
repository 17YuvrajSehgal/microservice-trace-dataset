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
and commit to the FIRST that clearly fires. `slow_db` is decided *last* — "slow answers" and
"activity collapse" are what a cap and a lossy path also produce, so db is only correct once the
others are ruled out.

**Last in the ORDER does not mean least likely.** `slow_db` is placed last because it must be
decided by a positive test (Check 5) rather than by elimination, not because it is a rare or
disfavoured answer. Reaching Check 5 with Checks 1–4 silent is the *expected* path for a slow
dependency — it is not a sign that the trace is healthy. Treat arriving there as normal progress
and run the test.

## Setup

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/fault.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/base.txt
```
`WINDOW_START` = where the rate shifts and stays shifted; `BASE_START` = a quiet stretch OUTSIDE
that window (far from both edges). If `idx_summary` shows no sustained change, still run the checks
on a mid-recording slice — a flat rate plot does NOT license `normal` on its own (a slow dependency
barely moves the event rate). `normal` has a hard bar; see "The bar for answering `normal`" below.

**A short dip is a window to investigate, never a reason to dismiss.** A fault can be continuous
(one sustained change) or intermittent (repeated short hits that recover in between). An
intermittent fault looks exactly like "a brief cross-container dip that rebounds" — so reasoning
"it only lasted a few seconds and recovered, therefore it is noise" throws away a real fault.
When the rate plot shows one or more short dips rather than a plateau:

```bash
# cut the WORST dip, not the middle of the recording: its deepest second is $DIP_START
bash $TOOLS/extract_slice.sh $TRACE $DAY $DIP_START 10 $WORK/fault.txt
```
Slice the **deepest dip** and run every check on that slice. If several dips repeat at a regular
cadence, that repetition is itself evidence of injection, not of noise. Only call a dip transient
after the checks have run on it and all come back clean.

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
FIRES if **one service's CPU use sits at a flat, low, sub-core value** — some fraction of a single
core, held steady across the window, well below what that service used in the baseline slice —
while the host CPUs are largely **IDLE** and that service has high **runnable wait**, and
`cpu_ceiling` shows a per-period ceiling below the period that collapsed from its baseline. Read
the fraction off the tool; do not expect any particular value. A service held at a fixed fraction
of a core while CPUs sit idle = a quota. → **`svc_cpu_cap`**.

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

**Check 5 — the slow-answer split: svc_net (delay) vs slow_db. THIS CHECK IS MANDATORY.**

If Checks 1–4 did not fire, you have ruled out four mechanisms and identified NOTHING. You are not
finished — you are at the point where the remaining two faults live. **Run `sock_lag` now. You may
not answer `normal`, and you may not answer at all, until it has run.** "No mechanism found in
Checks 1–4" is not evidence of health; `slow_db` and delay-only `svc_net` leave Checks 1–4 silent
*by construction* — that is what makes them the residue this check exists to split.

```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10    # expect: S-dominated, runnable wait low
python3 $TOOLS/sock_lag.py    $WORK/fault.txt 10 all # per-fd request-to-answer gaps vs baseline
python3 $TOOLS/sock_lag.py    $WORK/base.txt  10 all # the SAME command on the quiet slice
```
Compare the affected service's per-fd gaps against the baseline slice:
- gaps jumped ONLY on the connections **to one dependency** (e.g. a DB pool — a few fds to one
  peer), the service's other flows stay fast → that dependency is slow → **`slow_db`**.
- gaps jumped on **ALL or most of the service's flows/peers at once** (its callers' requests AND
  its own calls out) → the service's own network path is impaired (delay without loss) →
  **`svc_net`**, marked inferred. A database cannot slow down traffic that never touches it.
- gaps are **indistinguishable from baseline on every flow** → only now is nothing wrong.

A modest rise counts. You are comparing against this trace's own quiet stretch, so a consistent
gap increase on one peer's fds is the signal — do not hold out for a dramatic one.

If `sock_lag` cannot run or returns nothing usable, say so explicitly in the evidence and pick the
better-supported of `slow_db` / `normal` from the `sched_budget` row (S-dominated with little CPU
leans `slow_db`). Do not report `normal` while silently skipping the check.

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

## The bar for answering `normal` (read before you conclude)

`normal` means *"I ran the deciding test and the service's answer times match baseline."* It does
NOT mean *"I did not find anything."* The second is a report of your own effort, not a finding
about the trace. Four silent checks plus a skipped Check 5 is an unfinished investigation.

Before you may output `normal`, ALL of these must be true:
1. Checks 1–4 ran and were clearly absent.
2. **`sock_lag` actually ran** (Check 5) and the per-fd gaps are indistinguishable from baseline.
3. If the rate plot had any dip, you sliced the **deepest** one and the checks ran on THAT slice.

If you cannot satisfy (2), you do not have a `normal`. Say which check you could not run, and pick
the better-supported family from the evidence you do have.

## Output

Commit to exactly one `fault_type`. In the evidence, name which check fired and its number
(retransmission rate, runnable-wait rise + idle%, reclaim count, or per-fd sock_lag gap vs
baseline), **and state explicitly whether `sock_lag` ran**. Do not output `other`.
