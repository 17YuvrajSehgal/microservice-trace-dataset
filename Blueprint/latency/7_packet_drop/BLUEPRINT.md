<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: packet drops on a host

| | |
|---|---|
| Problem class | Network / reliability |
| Root cause this blueprint confirms or rejects | The host is **dropping packets** in its network stack, on receive or transmit, rather than delivering them |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. It needs `skb_kfree` and `skb_consume` events |
| Not used | Logs, request traces (spans), metrics, device/interface counters from outside the trace |

**When to use this.** Use it when the question is "is this box dropping packets?" rather than "is one service's TCP path lossy?". `svc_net` (blueprint 5) measures loss **indirectly**, through TCP retransmissions, and needs `net_dev_queue` events that carry the protocol headers. On a switch, router, or line-card, and on any trace recorded without header dissection, those headers are absent and most traffic is forwarded, non-TCP packets, so retransmission cannot be counted. This blueprint measures drops **directly**, from the kernel's own free events, and needs no headers.

**Status.** **Not yet calibrated on a labeled run.** There is no packet-drop trace with ground truth that is readable here, so this blueprint gives no fixed thresholds: it judges by the **shape** (rise vs baseline, real reason, burst that lines up with a receive dip). Treat its verdicts as qualitative until a labeled drop run calibrates the sizes. The event basis is confirmed: on the target traces `skb_kfree`, `skb_consume`, and `net_if_receive_skb` are all present in volume. There is no sweep on all runs and no results file. `net_drops.py` prints tables and `->` lines for a burst and a receive dip, no `VERDICT:` line. Agent: not run in the new form yet.

## Part 1. Background

A packet enters or leaves the host and the kernel **throws it away** instead of
delivering it. Real causes: a full or misconfigured queue (qdisc) discarding packets, a
receive ring overrun under load, a firewall/netfilter rule dropping traffic, no socket
for the destination, a checksum or header error, a congested forwarding path on a
switch/line-card.

The kernel frees every packet it finishes with, and it uses **two different events** to
say how it finished:

- `skb_consume`: the **normal** free. The packet was delivered or handled, then let go.
- `skb_kfree` (the kernel's `kfree_skb`): the packet was **dropped** or freed on an
  error path. On newer kernels it also carries a **`reason`** (`SKB_DROP_REASON_*`) that
  says why: `NO_SOCKET`, `TCP_*`, `NETFILTER_DROP`, `QDISC_DROP`, `OTHERHOST`, and so on.
  A reason of `NOT_SPECIFIED` means the kernel did not set one. That is frequently a
  benign free, not a true drop.

So a packet-drop fault is a **rise in `skb_kfree` relative to `skb_consume`**, usually
with a telling reason and clustered in time, and, on the receive side, **dips in
`net_if_receive_skb`** (fewer packets making it up the stack).

Three signals, which the decisive tool (`net_drops.py`) reads together:

1. **Drop share.** `skb_kfree / (skb_kfree + skb_consume)` rises above its quiet-period
   level. A few percent of steady background frees is normal; a sharp rise is not.
2. **Drop reason.** If the kernel records it, the top reason names the mechanism. A real
   reason (`QDISC_DROP`, `NETFILTER_DROP`, `NO_SOCKET`, a `TCP_*` code, an `RX_*` code)
   is a drop; `NOT_SPECIFIED` alone is weak evidence.
3. **Clustering and the receive dip.** Real drops **cluster in a window**, and receive
   drops show as a matching **dip in `net_if_receive_skb`**: the same second the drops
   spike, fewer packets arrive up the stack.

Problems that look similar:

- Normal background frees: `skb_kfree` a small, steady share of `skb_consume`, reason `NOT_SPECIFIED` (or none), no burst. A fault rises above baseline and/or carries a real reason.
- Workload wind-down / load stopped: receive AND transmit AND frees all fall together, smoothly. Drops rise while traffic continues; a wind-down drops nothing, it just does less.
- One service's degraded TCP path: retransmissions concentrated on one container's flows (needs headers). Hand to `svc_net` (blueprint 5). This blueprint counts raw drops, not retransmissions.
- CPU saturation / cap: a process waits for a CPU (`wait` high) or hits a quota ceiling. Hand to the CPU-cap / noisy-neighbor blueprints. Drops from CPU starvation are secondary; check CPU first if `wait` is high.
- Memory squeeze: memcg reclaim + disk re-reads. Hand to the memory-cap blueprint.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it is seconds | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time window into a decoded slice, keeping the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> [events_regex]` |
| `net_drops.py` | The decisive tool here. skb_kfree vs skb_consume, by reason, by process, over time, plus the net_if_receive_skb receive profile. Needs no protocol headers | `net_drops.py <slice.txt> <slice_seconds>` |
| `net_loss.py` | The TCP-retransmission check (needs headers). Used here only to hand a per-flow TCP case to `svc_net` | `net_loss.py <slice.txt> <slice_seconds> [min_segments]` |
| `sched_budget.py` | CPU/scheduler check. Used here only to rule a CPU cause in or out | `sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]` |
| `victim_info.py` | Who a process is | `victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]` |
| `wake_graph.py` | Who a process talks to | `wake_graph.py <sched_events.txt> <pid> [rows]` |

`DROPEV='skb_kfree|skb_consume|net_if_receive_skb|net_dev_queue|net_dev_xmit|sched_switch|sched_waking|sched_wakeup'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find when drops cluster, over the whole trace, and choose a quiet baseline time outside that window. (`orient`)

```
idx_summary.py $TRACE --rate 1
```

The last table is the trace data written per second, all events together. Look for
a window that stands out from the rest of the trace. What the README looks for is a
**window** where `skb_kfree` rises above the rest of the trace, and/or a **dip** in
`net_if_receive_skb` at the same time. Those per-event counts come from a count
index that is not a script of this folder, so the table here is only a hint.
Write the candidate window, or use the whole trace if drops look steady. base_start
is a quiet stretch OUTSIDE the window.
Read the health checks (lost events, gaps). Avoid stretches with loss, or say so.

Write down: `window_start` (start of the candidate window (or trace_start if drops look steady), HH:MM:SS only (no date)), `window_end` (end of the candidate window (or trace_end), HH:MM:SS only (no date)), `base_start` (a quiet stretch OUTSIDE the window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `window_found` | a window stands out |  | go to `measure` |
| `steady` | nothing stands out. Use the whole trace as the window and take a baseline time and a window time apart from each other |  | go to `measure` |

### Step 3. Measure the drops in a baseline slice and in one or two slices inside the window. This is the decisive step. (`measure`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/d_base.txt $DROPEV
extract_slice.sh $TRACE <day> <window_start> 10 $WORK/d_win.txt $DROPEV
net_drops.py $WORK/d_base.txt 10
net_drops.py $WORK/d_win.txt 10
```

net_drops.py prints the drop share, the top drop reasons, the owning processes, the
per-second burst, and the receive profile. It has no VERDICT line. It marks a burst
with a `-> BURST` line and a receive dip with a `-> RECEIVE DIP` line. Compare the
window slice with the baseline slice.
- Real drops: in the window, `skb_kfree` rises clearly above the baseline slice AND
  either carries a **real reason** (not `NOT_SPECIFIED`) or **bursts** in a second
  that lines up with a `net_if_receive_skb` **dip**. Record the reason, the
  per-second rate (window vs baseline), the window, and the owning process.
- Normal: `skb_kfree` is a small, steady share of `skb_consume`, reason
  `NOT_SPECIFIED` or none, no burst, no receive dip, and the window looks like the
  baseline.
- The drops carry a `TCP_*` reason: this may be a per-flow TCP path problem. Go on;
  the next step runs net_loss.py.
If the kernel records no reason, the tool says so. Judge by the rate, the clustering
in time, and the receive dips. That is weaker: it can miss a low, steady drop rate
that a reason would have named.
`net_if_receive_skb` missing only costs the receive-dip signal; `skb_kfree` and
`skb_consume` still give the drop count.
There are no fixed thresholds. `skb_kfree` is not only true drops: a rise with a
real reason, not the raw count, is the fault.

Write down: `drop_rate` (skb_kfree per second in the window slice and in the baseline slice, from net_drops.py), `drop_reason` (the top drop reason in the window slice, or "not recorded" if the kernel records none), `drop_owner` (the owning process (name) from net_drops.py).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `real_drops` | in the window, `skb_kfree` rises clearly above the baseline slice AND either carries a real reason (not `NOT_SPECIFIED`) or bursts in a second that lines up with a `net_if_receive_skb` dip |  | go to `lookalikes` |
| `normal` | `skb_kfree` is a small, steady share of `skb_consume`, reason `NOT_SPECIFIED` or none, no burst, no receive dip, and the window looks like the baseline |  | **Stop.** No packet-drop fault; frees are routine. Root cause **rejected**. |
| `no_events` | the tool finds no `skb_kfree` / `skb_consume` events in slices that were cut with the packet events | `no skb_kfree / skb_consume events in this slice ...` | **Stop.** This blueprint cannot measure drops. The fault is not observable in this recording. Root cause **inconclusive**. |

### Step 4. Rule out the lookalikes (a quiet period, CPU, a one-service TCP path, memory). (`lookalikes`)

```
sched_budget.py $WORK/d_win.txt 10
net_loss.py $WORK/d_win.txt 10
```

- Is it just a quiet period? Baseline vs window from the step before: drops rise
  while `skb_consume` / receive keep going. If everything fell together, it is a
  wind-down, not drops.
- Is it CPU? sched_budget.py on the window slice: is `wait` high? A packet-drop
  fault has `wait` near zero. If `wait` is high, drops may be a symptom of CPU
  starvation.
- Is it a one-service TCP path? Drop reasons and net_loss.py. Drops here are
  host-level with a stack reason, not TCP retransmissions on one flow. net_loss.py
  needs `net_dev_queue` headers; without them it finds no TCP segments and this
  check cannot be done.
- Is it memory? The memory blueprint's reclaim check: no memcg reclaim. No script
  of this folder does that check; if you did not run it, list it under "we did not
  check".
If a check does not fit, say which, and treat the verdict as unconfirmed.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `host_drops` | drops rise while `skb_consume` / receive keep going, `wait` is near zero, and the drops are host-level with a stack reason, not TCP retransmissions on one flow |  | go to `identify` Root cause **confirmed**. |
| `check_does_not_fit` | the drops are there, but one check does not fit. Say which |  | go to `identify` Root cause **unconfirmed**. |
| `wind_down` | receive, transmit and frees all fell together |  | **Stop.** It is a wind-down, not drops. A wind-down drops nothing, it just does less. Root cause **rejected**. |
| `cpu` | `wait` is high in the window slice |  | **Stop.** Drops may be a symptom of CPU starvation. Hand to the CPU-cap / noisy-neighbor blueprints and note the drops. Hand the case to blueprint `1_svc_cpu_cap`. Root cause **rejected**. |
| `tcp_one_path` | the drops carry a `TCP_*` reason, the trace has `net_dev_queue` headers, and net_loss.py shows TCP loss on one service's flows | `-> the ONE-PATH shape ...` | **Stop.** It is TCP per-flow, a one-service TCP path. Use `svc_net` (blueprint 5). Hand the case to blueprint `5_svc_net`. Root cause **rejected**. |

### Step 5. Identify where the drops land. (`identify`)

```
victim_info.py $WORK/d_win.txt 10 <pid of the top owning process>
wake_graph.py $WORK/d_win.txt <pid of the top owning process>
```

**Reason** is the strongest identity: it names the mechanism (`QDISC_DROP` = a queue
discipline, `NETFILTER_DROP` = a firewall rule, `NO_SOCKET` = nothing listening, an
`RX_*` code = the receive path).
Process / interface: the owning process from net_drops.py. If these are forwarding
daemons on a single-namespace host, name them and the receive path rather than a
"container" (there is none to name). A `pid_ns` of 0 for every event means no
per-container attribution is possible; say so.
net_drops.py prints the owning process by name. Take its pid from the
sched_budget.py table of the step before. victim_info.py and wake_graph.py on that
pid give its names and who it talks to.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the reason and the owning process are described |  | go to `report` |

### Report

fault_type: `packet_drop`.
Template: From [start] to [end] (UTC) this host was dropping packets: `skb_kfree` rose
to [rate]/s (baseline [rate]/s), reason [top reason], on [process / receive path], with
a matching dip in `net_if_receive_skb` at [time]. We ruled out [a quiet period / CPU / a
one-service TCP path / memory] because [reason]. We did not check [what was not tested].
Give the drop rate window vs baseline: the baseline is what makes the number mean
something. Quote the reason when the kernel records it; when it does not, say so and
lean on the burst + receive-dip alignment. Mark each claim Measured (the rates, the
reason, the window) or Inferred (why the drops happen; the trace shows the drop, rarely
the upstream cause). Say what you did not test.

## Part 4. Measured, and limits

- It confirms or rejects one thing: the host is dropping packets. It hands off to `svc_net` (per-flow TCP loss), the CPU-cap / noisy-neighbor blueprints (drops caused by CPU starvation), or the memory blueprint when the evidence points elsewhere.
- It needs `skb_kfree`. Without it, drops are not observable in the trace.
- **Drop reasons need a recent kernel** (~5.17+). On older kernels `skb_kfree` carries no reason; the tool falls back to rate + clustering + the receive dip, which is weaker — it can miss a low, steady drop rate that a reason would have named.
- **`skb_kfree` is not only true drops.** Some frees on normal-but-unusual paths also use it. That is why the reason and the baseline comparison matter — a rise with a real reason, not the raw count, is the fault.
- **No calibration numbers yet.** Thresholds here are qualitative (shape, not size) until a labeled packet-drop run is available to read. Always compare against a baseline slice.
- It says *that* the host drops packets and *where* (reason, process, path), not always *why* upstream (which rule, which link, which peer).
