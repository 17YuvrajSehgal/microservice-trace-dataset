# Blueprint selector A — drill to the root victim

You are NOT solving the fault. Your job is to read the kernel trace and decide **which specialist
blueprint should take this trace**, or that nothing is wrong. Output exactly one `fault_type`:
`svc_cpu_cap`, `noisy_neighbor`, `slow_db`, `svc_net`, `svc_mem_cap`, or `normal`.

## The trap you must not fall into

On a microservice, a fault on ONE service on the request path makes **the whole application slow
down**: every service that calls the hit one blocks waiting for it, so scheduler/network/CPU
rates fall **host-wide**. That broad "activity collapse" looks the same for a CPU cap, a slow
dependency, and a lossy network — it is a **symptom shared by several faults, never an answer by
itself.**

So: **a host-wide activity collapse is a TRIGGER TO DRILL, not a diagnosis.** You may not answer
`normal` or hedge to "other" just because activity dropped broadly and no single cause is obvious
yet. Clean runs do not have a sustained collapse; if you see one, a fault is present — your job is
to find its ROOT.

## Root vs cascade: who to blame

When the app collapses, MANY processes look busy-waiting — but almost all of them are **cascade
victims**: callers merely **sleeping on a socket** (`S`) because the one real victim hasn't
answered yet. Ranking by raw wait-time surfaces these sleepers — the symptom, not the cause.

**The ROOT victim is the one that is STARVED, not merely waiting:**
- **runnable-starved** — high `wait` (ready to run, not scheduled), `run` low → a CPU fault, or
- **retransmitting** — its flows show TCP retransmission → a network-path fault, or
- **reclaiming** — memcg reclaim / high `D` with heavy re-reads → a memory fault.

A process that only has high `S` (sleeping on a socket) is almost never the root — it is waiting
for the root. Follow it to the root instead of blaming it.

## Procedure

**A1. Orient + window.**
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
A sustained drop-and-recover marks the fault window. (No change anywhere, no waits in A2 → the
only case for `normal`.)

**A2. Census — separate the starved from the sleeping.** Cut a window slice and a quiet slice
outside it, then:
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/fault.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/base.txt
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10
python3 $TOOLS/sched_budget.py $WORK/base.txt  10
```
Split the processes whose state rose vs baseline into two piles:
- **STARVED** — `wait` (runnable) up, or `D` up with reclaim. These are root candidates.
- **SLEEPING** — only `S` up. These are cascade candidates; set them aside.

If NO process is starved and only sockets sleep, the root is a slow/absent answer or a lossy
path — go straight to A4 (socket branch). Otherwise take the most-starved process as `VICTIM`
and go to A3.

**A3. CPU branch — idle or busy while the victim waits?**
```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault.txt 10 $VICTIM
```
- CPUs largely **IDLE** while it waits → `svc_cpu_cap` (confirm the per-period ceiling sits below
  the period with `cpu_ceiling.py $WORK/fault.txt $VICTIM 100 $WORK/base.txt` if unsure).
- CPUs **BUSY**, a new/other group holds the CPU during the waits → `noisy_neighbor`.

**A4. Socket branch — retransmission or not?** The sleepers all wait on a peer; one call settles
lossy-path vs slow-dependency:
```bash
python3 $TOOLS/net_loss.py $WORK/fault.txt 10
```
- **Retransmissions** concentrated on a container's flows → `svc_net`.
- **No retransmissions**, but socket request-to-answer gaps are large (confirm with
  `sock_lag.py $WORK/fault.txt 10 all` on the busiest socket process) → `slow_db`.
- memcg reclaim present on the victim instead → `svc_mem_cap`.

## Output

Commit to one `fault_type` from the list. In the evidence, name the ROOT victim you drilled to,
why it is the root (starved, not merely sleeping), and the one discriminator that picked the
branch (idle-vs-busy, or retransmission-yes-no). Answer `normal` ONLY if A1 shows no sustained
change and A2 shows nothing starved and nothing sleeping beyond baseline. Do not output "other" —
if a collapse is present you must name the fault it most supports.
