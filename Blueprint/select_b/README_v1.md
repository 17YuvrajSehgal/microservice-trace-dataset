# Blueprint selector B — fingerprint panel

You are NOT solving the fault. Decide **which specialist blueprint should take this trace**, or
that nothing is wrong. Output exactly one `fault_type`: `svc_cpu_cap`, `noisy_neighbor`,
`slow_db`, `svc_net`, `svc_mem_cap`, or `normal`.

## The idea: test each mechanism directly, don't rank victims

A fault on one request-path service makes the whole app slow, so a **host-wide activity collapse**
looks the same for several faults and tells you little. Instead of arguing about which process is
the victim, **run each fault's own direct check and see which fingerprint is actually present.**
Each check below is a distinct, mostly victim-agnostic question. Run the cheap ones first; a
collapse means at least one WILL fire — find which.

## B0. Orient + one window slice

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/fault.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/base.txt
```
If `idx_summary` shows no sustained change at all, run B1-B5 on a mid-recording slice anyway; only
answer `normal` if every check below comes back absent.

## The panel — run each, record PRESENT / ABSENT + strength

**B1. Retransmission? (svc_net)** — direct, victim-agnostic.
```bash
python3 $TOOLS/net_loss.py $WORK/fault.txt 10
```
PRESENT if retransmissions concentrate on one container's flows, clearly above the baseline slice.

**B2. Memory reclaim? (svc_mem_cap)** — direct, victim-agnostic.
```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10   # look for high D, and for memcg/vmscan events
grep -c -E "mm_vmscan|memcg|reclaim" $WORK/fault.txt
```
PRESENT if memcg-reclaim events fire and a process re-reads heavily with high `D`. (If the trace
carries no memory events at all, this fault cannot be seen — ABSENT, say so.)

**B3. CPU withheld while idle? (svc_cpu_cap)** — scan the top CPU-waiter, no need to know who it is.
```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10    # pick the top runnable-wait riser as C
python3 $TOOLS/cpu_hogs.py   $WORK/fault.txt 10 $C
python3 $TOOLS/cpu_ceiling.py $WORK/fault.txt $C 100 $WORK/base.txt
```
PRESENT if that process waits runnable **while the CPUs are largely IDLE** and its per-period
on-CPU ceiling sits below the period and below its baseline (CPU available but withheld = quota).

**B4. New CPU hog while busy? (noisy_neighbor)** — direct from the hog table.
```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault.txt 10
python3 $TOOLS/cpu_hogs.py $WORK/base.txt  10
```
PRESENT if the CPUs are **BUSY** and a process/group that was absent or tiny in baseline now holds
a large share, arriving with the window.

**B5. Slow answers without loss? (slow_db)** — only meaningful if B1 was ABSENT.
```bash
python3 $TOOLS/sock_lag.py $WORK/fault.txt 10 all
python3 $TOOLS/sock_lag.py $WORK/base.txt  10 all
```
PRESENT if a process's socket request-to-answer gaps jump far above baseline on one dependency's
connections while answers still arrive, AND B1 found no retransmission.

## Decide — strongest fingerprint wins

Pick the one check that fired cleanly. If several fired, use this precedence (most specific
mechanism first), and say what you set aside and why:

1. **B1 retransmission present** → `svc_net` (loss leaves retransmissions; a merely-slow peer does not).
2. **B2 reclaim present** → `svc_mem_cap`.
3. **B3 runnable-starved while idle** → `svc_cpu_cap` (idle CPUs rule out competition).
4. **B4 busy + new hog** → `noisy_neighbor`.
5. **B5 slow answers, no loss** → `slow_db`.
6. none fired → `normal`.

Note the near-miss: B3 (cap, CPUs idle) vs B4 (neighbor, CPUs busy) are separated by idle-share;
B1 (net, retransmission) vs B5 (db, no retransmission) by the retransmission count. State the
number that decided it. Do not output "other".
