# Blueprint selector — which fault is this?

You are NOT solving the fault here. Your one job is to read the kernel trace cheaply and decide
**which specialist blueprint should take this trace** — or that nothing is wrong. You have a small
set of fast tools. Do the least work needed to commit to one answer.

The candidates (and the only labels you may output as `fault_type`):

| label | the specialist blueprint it routes to |
|---|---|
| `svc_cpu_cap` | a cgroup CPU quota throttles one container |
| `noisy_neighbor` | another workload steals the CPU |
| `slow_db` | a dependency answers slowly over a socket |
| `svc_net` | one container's network path loses/delays packets |
| `svc_mem_cap` | a cgroup memory limit reclaims or kills |
| `normal` | nothing is wrong — do not force a choice |

## The one question that separates them: what is the victim waiting ON?

The scheduler records, for every task that stops running, WHY it stopped. That single fact splits
the whole field:

- **Runnable-wait** — the task is ready to run but is not given a CPU. It wants CPU.
  → `svc_cpu_cap` or `noisy_neighbor`.
- **Sleeping on a socket (`S`)** — the task is parked waiting for an answer from the network.
  → `slow_db` or `svc_net`.
- **Memory reclaim / heavy re-reads / uninterruptible `D`** — the task is fighting for memory.
  → `svc_mem_cap`.
- **Nothing waits, nothing changed** → `normal`.

So: find the victim, read what it is waiting on, then fire ONE discriminator to pick the leaf.

## Fingerprints — the minimal signature of each (match against these, do not over-solve)

| label | Applies when (first-order signature) |
|---|---|
| `svc_cpu_cap` | a victim waits **runnable** for the CPU **while the CPUs are largely IDLE** — CPU is available but withheld. Its on-CPU-per-period sits below the full period. One container (a whole process tree) is hit. |
| `noisy_neighbor` | a victim waits **runnable**, but the **CPUs are BUSY** — a **new** process or named group appeared and is holding the CPU, arriving exactly with the victim's waits. |
| `slow_db` | the victim does **not** wait for CPU and does **not** wait on its own disk; it **sleeps on a socket**, its request-to-answer gap jumps on the connections to one dependency, answers still arrive but late, and there are **zero retransmissions**. |
| `svc_net` | callers sleep on sockets AND there are **TCP retransmissions** concentrated on one container's flows; its throughput collapses. Retransmission is what separates a lossy path from a merely slow dependency. |
| `svc_mem_cap` | **memcg reclaim** by one container's processes, the same pages re-read many times, `D` high; processes may exit under a hard limit. (If the trace carries no memory events at all, this fault cannot be seen here — say so.) |
| `normal` | after finding the window and the top waiter, nothing waits beyond baseline and no rate change persists. |

## Triage procedure (cheap — stop as soon as one fingerprint clearly matches)

**T0. Orient and find the incident window.**
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
A persistent change in the rate marks the window. If nothing changes anywhere, lean `normal` but
still do T1 on a mid-recording slice before concluding.

**T1. Find the victim and read what it waits on.** Cut one slice inside the window and one quiet
slice well outside it, then run the scheduler census:
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/fault.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/base.txt
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10
python3 $TOOLS/sched_budget.py $WORK/base.txt  10
```
Rank processes by the rise in `wait` (runnable-wait) and in `S`/`D` versus baseline. The top
riser is your victim. Read its columns:
- `wait` and the long-wait counts jump, `run` low → **runnable-wait** → go to T2-CPU.
- `S` jumps, `wait` stays low → **sleeping for an answer** → go to T2-NET.
- `D` jumps and reads are heavy / reclaim present → **memory** → `svc_mem_cap`.
- nothing rises → `normal`.

**T2-CPU. Idle or busy while it waits?** One call decides cap vs neighbor:
```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault.txt 10 $VICTIM
```
- CPUs largely **IDLE** while the victim waits → `svc_cpu_cap`.
- CPUs **BUSY**, a new/other group holds the CPU during the waits → `noisy_neighbor`.

**T2-NET. Retransmissions or not?** One call decides lossy-path vs slow-dependency:
```bash
python3 $TOOLS/net_loss.py $WORK/fault.txt 10
```
- **Retransmissions** concentrated on a container's flows → `svc_net`.
- **No retransmissions**, but the socket answers are slow (confirm with `sock_lag.py` on the
  victim's fds if unsure) → `slow_db`.

## Output contract

Commit to exactly one `fault_type` from the table above (use the label verbatim). Give your
confidence and, in the evidence, name the ONE fingerprint you matched and the numbers that matched
it (which wait rose, idle-vs-busy, retransmission yes/no). Do not run a full root-cause
investigation; do not name the exact quota or delay. If two leaves remain genuinely tied after the
branch discriminator, say which two and pick the better-supported one. If nothing waits, answer
`normal` — a forced guess on a clean trace is a wrong answer.
