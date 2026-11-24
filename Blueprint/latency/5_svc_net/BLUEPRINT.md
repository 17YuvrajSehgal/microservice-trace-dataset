<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a degraded network path of one service (svc_net), or queues that drop on many senders (host-wide)

| | |
|---|---|
| Problem class | Latency |
| Root cause this blueprint confirms or rejects | ONE service's network path is degraded. Its packets are delayed or dropped on the way in or out |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. It needs `net_dev_queue` events with protocol headers |
| Not used | Logs, request traces (spans), metrics, container settings |

**When to use this.** One service is slow and every service that calls it slows down with it, but there is no error message anywhere: TCP hides this from every log and every application error counter. The machine's network is fine and the other services talk normally. The trace usually writes less data per second.

**Status.** `net_loss.py` was changed on 17-11-2026 and re-measured on 79 slices of two applications: 0 dropped in 36 healthy slices; on 10 one-container runs 100% of the drops are at the injected container; on 16 host-wide runs 8-10 senders drop (one application) and 7-13 (the other). This folder has no sweep of the tool on all runs and no results file. `net_loss.py` prints tables and one `->` summary line, no `VERDICT:` line. The numbers of the solved case (4 retransmits in 90,107; 1.4-3.2% per flow) were measured with the tool before the change; read them as "near zero when healthy, clearly above when degraded". The README does not use the family names: it says "degraded path of one service" and "host-wide network problem". The scheduler step and the lookalike checks were written on one solved case. Agent: not run in the new form yet.

## Part 1. Background

One service's network path goes bad. The machine's network is fine, the other services
talk normally, but packets to or from this one container are being **dropped**,
**delayed**, or both. Causes in real systems: a bad traffic-shaping rule on the
container's interface, a broken overlay tunnel, a flaky virtual link, a mis-set firewall
or rate limit.

TCP hides this from every log and every application error counter. When a packet is
lost, TCP silently sends it again (a **retransmission**) and waits. When the path is
slow, TCP just waits longer. The kernel records every packet it sends, with its TCP
sequence number. A segment sent twice with the same sequence number is a retransmission.

Every segment is seen at two devices on its way: the sender's own interface, then the
receiver's side. `net_loss.py` uses that to tell two kinds of retransmit apart:

| Kind | What the trace shows | Meaning |
|---|---|---|
| **DROPPED** | the segment appears more often at the first device than at the second | the sender's own queue threw a copy away. **This is the loss signal** |
| sent twice | both copies reach the second device | nothing was lost on the way out; an ACK was late and the kernel sent a probe. **Healthy systems have these**: 50-110 per 10 s on one application, 3-22 on the other |

Measured: **0 dropped in 36 healthy slices** (before a fault, or fault-free runs).

Two effects, usually together. Retransmissions on the victim's flows, in both
directions, because the victim's lost replies also make its peers resend. And a
throughput collapse: waiting on timeouts and a delayed path means far fewer requests
complete, and every service that calls the victim slows down with it. The rest of the
machine is healthy: no CPU waits, no disk waits, no reclaim. The victim's own threads
mostly SLEEP (`S`), waiting on sockets.

One trap: a packet crossing from a container to the host fires the transmit event once
per network device. Counted naively, every segment looks sent twice, a fake "50%
retransmission" on every healthy flow. The tool counts each flow at ONE observation point.

The sender of a flow is the process and container that **own the source address**, not
whoever was on the CPU when the packet left (a delayed or retransmitted segment leaves
from a timer, and would read as `swapper`).

Problems that look similar:

- Host-wide network problem: flows of MANY unrelated containers retransmit. One service's path hits one container's flows only.
- Slow dependency (no loss): the victim's callers sleep (`S`) on sockets, but zero retransmission anywhere. Loss always leaves retransmissions. No retransmissions = the peer is slow, not the path lossy.
- The peer is CPU-capped or overloaded: the slow service shows CPU waits (`wait`) or a quota ceiling; flows are clean. Hand it to the CPU-cap or noisy-neighbor blueprint.
- The peer is memory-squeezed: memcg reclaim and disk re-reads on the peer; flows are clean. Hand it to the memory-cap blueprint.
- Connection failures (pool/fd exhaustion): new connections fail outright; existing flows are clean. A degraded path degrades EXISTING flows.
- Pure added delay, no loss: throughput collapses and callers sleep, but retransmission stays near zero. Possible and real. Retransmission proves loss, its absence does not prove the path is clean. Say "delay suspected, loss not shown".

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it takes seconds | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice and keeps the events you name (default: scheduling only; this blueprint passes a network pattern) | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> [events_regex]` |
| `net_loss.py` | The decisive tool here. Retransmissions per flow and per sending container, counted at one observation point, plus packet frees | `net_loss.py <slice.txt> <slice_seconds> [min_segments]` |
| `sched_budget.py` | Time budget per process: running, waiting, sleeping (`S`), disk sleep (`D`) | `sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]` |
| `wake_graph.py` | Which processes wake the victim, and which ones it wakes: who talks to whom | `wake_graph.py <sched_events.txt> <pid> [rows]` |
| `victim_info.py` | Who a process is: PID, names, threads, container | `victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]` |

`NETEV='sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find when something changed. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. A degraded path usually makes the
rate **fall**: requests are stuck, less work happens, fewer events. Write down the
candidate window. Use trace_start and trace_end if nothing stands out.
Read the health checks (lost events, gaps). Avoid stretches with loss, or say so.

Write down: `window_start` (first row where the rate changed (or trace_start if nothing stands out), HH:MM:SS only (no date)), `window_end` (first row where it was back to normal (or trace_end), HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `window_found` | the rate fell (or changed) for a stretch of time |  | go to `map_loss` |
| `no_clear_change` | nothing stands out. Set window_start = trace_start and window_end = trace_end |  | go to `map_loss` |

### Step 3. Find out whether any path is lossy, and whose, and what it did to the traffic. This is the decisive measurement. (`map_loss`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/n_base.txt $NETEV
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/n_f1.txt $NETEV
extract_slice.sh $TRACE <day> <a second time in the window> 10 $WORK/n_f2.txt $NETEV
net_loss.py $WORK/n_base.txt 10
net_loss.py $WORK/n_f1.txt 10
net_loss.py $WORK/n_f2.txt 10
```

Cut one baseline slice and two or three inside the window, keeping the network events.
net_loss.py prints the overall retransmission rate, the worst flows with their
senders and containers (`net_ns`), and a per-container summary. It has no VERDICT
line. The line `Senders whose own queue dropped segments: K of N` and the line under
it answer the one-service or host-wide question.
- Healthy: 0 DROPPED. `sent twice` alone is not a fault.
- (Nearly) all drops at ONE sender's queue (the `-> the ONE-PATH shape` line): that
  container's path is degraded. Measured on 10 one-container runs of two
  applications: 100% of the drops at the injected container, 236-283 drops per 10 s
  on one application and 5-19 on the other. Its peers show `sent twice` toward it.
  Write down the container (`net_ns`) and its addresses.
- Many unrelated senders drop (the `-> the HOST-WIDE shape` line): the problem is
  host-wide (the machine's own link, a shared bridge, or the same shaping rule on
  every container), not one service's path. Measured on 16 host-wide runs: 8-10
  senders drop and the largest holds 21-28% (one application, 10 s); 7-13 senders
  (the other, 30 s).
- Under 20 drops: the tool says the shares are too few to trust. That happens when
  traffic has collapsed (measured: about 1,000 segments per 10 s instead of 60,000
  or more). Cut a 30 s slice and run it again.
- No drops anywhere, in any slice: no loss is visible. The next step checks whether
  a service is still slow and its callers sleep on sockets.
- `no TCP data segments found`: the trace has no `net_dev_queue`, or records it
  without the protocol headers. This blueprint cannot count retransmissions then.
The baseline slice of a degraded trace also prints the "no queue drops" line. That
is expected; judge the slices inside the window.
On the ONE-PATH shape, measure the collapse from the same outputs: compare the same
flows in the baseline and fault outputs (segments per flow, and total segments).
Measured on the solved case: the victim's database flow fell from 1,173 segments per
10 s to about 60, and the total from 90,107 to 30,988 per 10 s. If the victim's flows
did NOT shrink, the loss is real but mild: say "degraded but keeping up".

Write down: `base_start` (start of the baseline slice, HH:MM:SS only (no date)), `fault_start` (start of a slice inside the window, HH:MM:SS only (no date)), `victim_ns` (the container whose queue dropped segments (the `net_ns` on the `->` line of net_loss.py)), `victim_ip` (its address, from the flow lines of net_loss.py), `collapse` (segments of the victim's flows and total segments, baseline against fault; or "degraded but keeping up" if the flows did not shrink).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `one_path` | a slice inside the window reads the ONE-PATH shape. (Nearly) all drops are at one sender's queue, and that container's path is degraded | `-> the ONE-PATH shape ...` | go to `sched_view` |
| `host_wide` | a slice inside the window reads the HOST-WIDE shape. Many unrelated senders drop at their own queues | `-> the HOST-WIDE shape ...` | **Stop.** Not one service's path. Report it as a host-wide network problem and list the senders. Root cause **confirmed** (`anomaly_net`). |
| `no_drops` | no queue drops packets, in any slice. No loss is visible. The next step checks for a slow peer or pure delay | `no queue drops packets here ...` | go to `sched_view` |
| `no_segments` | the tool finds no TCP data segments in slices that were cut with the network events | `no TCP data segments found ...` | **Stop.** This blueprint cannot count retransmissions on this trace. Only the indirect signs remain (callers sleeping, throughput collapse). Say clearly that loss could not be measured. Root cause **inconclusive**. |

### Step 4. A second, independent view: the victim and its callers should be SLEEPING on sockets, not computing. Then rule out the lookalikes. (`sched_view`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/baseline_slice.txt
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/fault_slice.txt
sched_budget.py $WORK/fault_slice.txt 10
sched_budget.py $WORK/baseline_slice.txt 10
wake_graph.py $WORK/fault_slice.txt <pid of a caller>
```

sched_budget.py prints one row per process: `run`, `wait` (CPU), `S` (sleep), `D`
(disk). The victim's processes and its callers show high `S` and LOW `run` in the
fault slice: everyone is waiting for the network. `wait` and `D` stay near zero.
wake_graph.py on a caller shows who it talks to. It is useful to confirm the
sleepers are the victim's callers and not unrelated.
Find the victim's own process (the sender name from net_loss.py) in the table and
write down its pid.
The lookalike checks:
- Is it host-wide? Only the victim's container drops. Everyone else at about 0%.
- Is the peer just slow (no loss)? Drops present. No drops = do not claim loss.
- Is it the victim's CPU? `wait` near zero. The victim sleeps, it does not queue
  for a CPU.
- Is it disk or memory? `D` near zero, no reclaim (the memory blueprint's reclaim
  check).
- Did traffic simply stop? Collapsed traffic WITH retransmissions. Traffic that
  just ends (load stopped) retransmits nothing.
If one check does not fit, say which one in your report, and treat the verdict as
unconfirmed.

Write down: `victim_pid` (pid of one of the victim's own processes (the sender name from net_loss.py, looked up in the sched_budget.py table)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `path_degraded` | the step before read the ONE-PATH shape, and here the victim's processes and its callers show high `S` and low `run`, with `wait` and `D` near zero. The lookalike checks fit |  | go to `identify` Root cause **confirmed**. |
| `check_does_not_fit` | the step before read the ONE-PATH shape, but one of the lookalike checks does not fit. Say which one |  | go to `identify` Root cause **unconfirmed**. |
| `cpu_problem` | `wait` is high on the victim |  | **Stop.** The "network problem" is actually a CPU problem on the victim. Hand the case to the CPU-cap / noisy-neighbor blueprints. Hand the case to blueprint `1_svc_cpu_cap`. Root cause **rejected**. |
| `disk_or_memory` | `D` is high |  | **Stop.** Look at the disk/memory blueprints instead. Hand the case to blueprint `4_svc_mem_cap`. Root cause **rejected**. |
| `no_loss_shown` | the step before found no drops in any slice. A service is still slow and its callers sleep on sockets, or nothing stands out here either |  | **Stop.** No loss shown. A slow peer or added delay cannot be separated from the trace alone. If traffic collapsed and callers sleep, say "delay suspected, loss not shown". Root cause **inconclusive**. |

### Step 5. Identify the victim, as precisely as the trace allows. (`identify`)

```
victim_info.py $WORK/fault_slice.txt 10 <victim_pid>
wake_graph.py $WORK/fault_slice.txt <victim_pid>
```

Same honesty rules as the other blueprints: process name and PID always; the
container namespaces if recorded (a 0 means "could not be read"). The addresses and
ports from net_loss.py are part of the identity here: "the container at `172.x.y.z`
whose flows to its database at `:27017` retransmit" is concrete and checkable.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the victim is described |  | go to `report` |

### Report

fault_type: `svc_net` for one service's path. If net_loss.py read the HOST-WIDE shape,
report a host-wide network problem (`anomaly_net`) and list the senders.
Template: From [start] to [end] (UTC), [victim container] was slow because its network
path was degraded. We know because [evidence 1: its flows' retransmission rates against
the zero baseline], [evidence 2: its throughput collapse], and [evidence 3: its callers
sleeping on sockets while CPU and disk stayed clean]. We ruled out [host-wide network,
CPU, disk/memory] because [reason]. We did not check [what was not tested].
Name the victim, the window, the flows, and the measured rates. Give at least two
independent pieces of evidence: the retransmission map, the collapse, the scheduler view.
Mark each claim Measured or Inferred. Say what you did not test.
Loss: the per-flow retransmission rates are your measurement of it. Quote them per
direction. The configured loss is not readable from the trace; your measured rate is a
floor, not the exact setting, because retransmission also rises from jitter and reordering.
Delay: the trace shows its consequences (collapse, sleeping callers), not the delay
itself. Added delay is always Inferred. Mark it when the collapse is far larger than the
loss rate explains (measured: 4% configured loss, but a 20x throughput collapse, which
only the added round-trip delay explains).
Direction: if only the flows OUT of the victim retransmit, the damage is on its egress;
both directions usually means the path itself (its interface or link).
The trace cannot say WHY the path is degraded (a shaping rule, a bad link, a tunnel).

## Part 4. Measured, and limits

- It confirms or rejects one cause: a degraded network path of one service. It stops and says so when the evidence points at host-wide trouble, the CPU, the disk, or a merely slow peer.
- It needs `net_dev_queue` events **with protocol headers**. Without them, loss cannot be measured — only inferred from sleeping callers, which a slow peer also explains.
- **Pure delay with zero loss leaves no retransmission.** This blueprint can then only say "collapse without a local cause"; it cannot prove the path added delay.
- A packet crossing container-to-host fires the transmit event once per device. Counting naively reads as a fake 50% retransmission on every flow — measured on a healthy baseline. `net_loss.py` counts each flow at one observation point for exactly this reason.
- The measured rates (0% healthy; 1.4–3.2% per flow under 4% configured loss with 150 ms delay) come from one system. Use them as a feel for the sizes, not as thresholds; always compare against your own baseline slice.
- UDP loss leaves no retransmission at all. This blueprint is about TCP traffic.
- It cannot say WHY the path is degraded (a shaping rule, a bad link, a tunnel) — only that it is, and whose it is.
