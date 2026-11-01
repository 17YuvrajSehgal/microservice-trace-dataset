# Blueprint: finding packet drops on a host from a kernel trace

| | |
|---|---|
| Problem class | Network / reliability |
| Root cause this blueprint confirms or rejects | The host is **dropping packets** in its network stack — on receive or transmit — rather than delivering them |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder |
| Also allowed | The list of event types the trace holds (read from `metadata`) |
| Not used | Logs, request traces (spans), metrics, device/interface counters from outside the trace |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

**When to reach for this instead of `svc_net`.** `svc_net` (blueprint 5) measures loss **indirectly**, through TCP retransmissions, and needs `net_dev_queue` events that carry the protocol headers. On a switch, router, or line-card — and on any trace recorded without header dissection — those headers are absent and most traffic is forwarded, non-TCP packets, so retransmission cannot be counted. This blueprint measures drops **directly**, from the kernel's own free events, and needs no headers. Use it when the question is "is this box dropping packets?" rather than "is one service's TCP path lossy?".

---

## Part 1. Background

### 1.1 What the fault is

A packet enters or leaves the host and the kernel **throws it away** instead of delivering it. Real causes: a full or misconfigured queue (qdisc) discarding packets, a receive ring overrun under load, a firewall/netfilter rule dropping traffic, no socket for the destination, a checksum or header error, a congested forwarding path on a switch/line-card.

The kernel frees every packet it finishes with, and it uses **two different events** to say how it finished:

- `skb_consume` — the **normal** free: the packet was delivered or handled, then let go.
- `skb_kfree` (the kernel's `kfree_skb`) — the packet was **dropped** or freed on an error path. On kernels from ~5.17 on, it also carries a **`reason`** (`SKB_DROP_REASON_*`) that says *why*: `NO_SOCKET`, `TCP_*`, `NETFILTER_DROP`, `QDISC_DROP`, `OTHERHOST`, and so on. A reason of `NOT_SPECIFIED` means the kernel did not set one — frequently a benign free, not a true drop.

So a packet-drop fault is a **rise in `skb_kfree` relative to `skb_consume`**, usually with a telling reason and clustered in time, and — on the receive side — **dips in `net_if_receive_skb`** (fewer packets making it up the stack).

### 1.2 What it looks like in a kernel trace

Three signals, which the decisive tool (`net_drops.py`) reads together:

1. **Drop share.** `skb_kfree / (skb_kfree + skb_consume)` rises above its quiet-period level. A few percent of steady background frees is normal; a sharp rise is not.
2. **Drop reason.** If the kernel records it, the top reason names the mechanism. A real reason (`QDISC_DROP`, `NETFILTER_DROP`, `NO_SOCKET`, a `TCP_*` code, an `RX_*` code) is a drop; `NOT_SPECIFIED` alone is weak evidence.
3. **Clustering and the receive dip.** Real drops **cluster in a window**, and receive drops show as a matching **dip in `net_if_receive_skb`** — the same second the drops spike, fewer packets arrive up the stack.

> **Not yet calibrated on a labeled run.** The existing blueprints quote measured numbers from a known-fault trace. We do **not** have a packet-drop trace with ground truth that is readable here, so this blueprint gives no fixed thresholds — it judges by the **shape** (rise vs baseline, real reason, burst that lines up with a receive dip). Treat its verdicts as qualitative until a labeled drop run calibrates the sizes. The event basis is confirmed: on the target traces `skb_kfree`, `skb_consume`, and `net_if_receive_skb` are all present in volume.

### 1.3 Problems that look similar

| Cause | What the kernel trace shows | How it differs from packet drops |
|---|---|---|
| **Packet drops (this fault)** | `skb_kfree` rises vs `skb_consume`, with a real reason and/or a burst that lines up with a `net_if_receive_skb` dip | — |
| Normal background frees | `skb_kfree` a small, steady share of `skb_consume`, reason `NOT_SPECIFIED` (or none), no burst | A fault rises above baseline and/or carries a real reason |
| Workload wind-down / load stopped | Receive AND transmit AND frees all fall together, smoothly | Drops rise while traffic continues; a wind-down drops nothing, it just does less |
| One service's degraded TCP path | Retransmissions concentrated on one container's flows (needs headers) | Hand to `svc_net` (blueprint 5). This blueprint counts raw drops, not retransmissions |
| CPU saturation / cap | A process waits for a CPU (`wait` high) or hits a quota ceiling | Hand to the CPU-cap / noisy-neighbor blueprints. Drops from CPU starvation are secondary — check CPU first if `wait` is high |
| Memory squeeze | memcg reclaim + disk re-reads | Hand to the memory-cap blueprint |

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/` | Everything comes from here |
| `skb_kfree` and `skb_consume` events | The drop count and the normal-free baseline |
| `net_if_receive_skb` events | The receive-path profile, to catch the dip |
| A normal period to compare with: a quiet stretch in the same trace, or a fault-free trace of the same system | The baseline is what makes a drop rate mean something |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |

The scripts (same shared set as the other blueprints, plus `net_drops.py`):

| Script | What it does |
|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it is seconds |
| `idx_slice.py`, `extract_slice.sh` | Cut one time window into a small trace / decoded slice, keeping the events you name |
| `net_drops.py` | **The decisive tool here:** skb_kfree vs skb_consume, by reason, by process, over time, plus the net_if_receive_skb receive profile. Needs no protocol headers |
| `net_loss.py` | The TCP-retransmission check (needs headers) — used here only to hand a per-flow TCP case to `svc_net` |
| `sched_budget.py`, `cpu_hogs.py`, `rhythm.py`, `cpu_ceiling.py` | CPU/scheduler checks; used here only to rule a CPU cause in or out |
| `victim_info.py`, `wake_graph.py` | Who a process is, and who it talks to |

The slice pattern this blueprint uses (packet frees + receive + transmit + scheduling):

```bash
DROPEV='skb_kfree|skb_consume|net_if_receive_skb|net_dev_queue|net_dev_xmit|sched_switch|sched_waking|sched_wakeup'
```

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the scripts
WORK=/path/to/scratch      # an empty folder for slices and notes
DROPEV='skb_kfree|skb_consume|net_if_receive_skb|net_dev_queue|net_dev_xmit|sched_switch|sched_waking|sched_wakeup'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_slice.py,extract_slice.sh,net_drops.py} > /dev/null && echo "scripts found"
```

Both lines must print OK.

---

## Part 4. Procedure

### Step 1. Check the trace and that the events exist

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -E 'skb_kfree|skb_consume|net_if_receive_skb' $WORK/event_names.txt
```

- Read the health checks (lost events, gaps). Avoid stretches with loss, or say so.
- If the trace has **no `skb_kfree`**, this blueprint cannot measure drops — say so and stop (the fault is not observable in this recording).
- `net_if_receive_skb` missing only costs the receive-dip signal; `skb_kfree` + `skb_consume` still give the drop count.

**Next:** Step 2.

### Step 2. Find when drops cluster, over the whole trace

Use the count index (fast) to see the drop and receive rates across the whole recording before cutting anything:

```bash
# per-bucket counts straight from the index - no decode needed
python3 $TOOLS/idx_summary.py $TRACE --rate 1 | sed -n '/^data written per/,$p'
```

(The agent's own `ctf_timeline`/`query_ctf` tools read the same index: get the per-bucket series for `skb_kfree`, `skb_consume`, and `net_if_receive_skb` over the full span.) Look for:

- a **window** where `skb_kfree` rises above the rest of the trace, and/or
- a **dip** in `net_if_receive_skb` at the same time.

Write the candidate window (or use the whole trace if drops look steady):

```bash
WINDOW_START=<HH:MM:SS>
WINDOW_END=<HH:MM:SS>
BASE_START=<HH:MM:SS>     # a quiet stretch OUTSIDE the window
```

**Next:** Step 3.

### Step 3. Measure the drops (the decisive step)

Cut a baseline slice and one or two inside the window, keeping the packet events, then run `net_drops.py`:

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/d_base.txt "$DROPEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/d_win.txt  "$DROPEV"

python3 $TOOLS/net_drops.py $WORK/d_base.txt 10
python3 $TOOLS/net_drops.py $WORK/d_win.txt  10
```

`net_drops.py` prints the drop share, the top drop reasons, the owning processes, the per-second burst, and the receive profile.

Read it:

- **Real drops:** in the window, `skb_kfree` rises clearly above the baseline slice AND either carries a **real reason** (not `NOT_SPECIFIED`) or **bursts** in a second that lines up with a `net_if_receive_skb` **dip**. Record the reason, the per-second rate (window vs baseline), the window, and the owning process. Go to Step 4.
- **Normal:** `skb_kfree` is a small, steady share of `skb_consume`, reason `NOT_SPECIFIED` or none, no burst, no receive dip, and the window looks like the baseline. Report "no packet-drop fault; frees are routine" and **stop**.
- **The drops carry a `TCP_*` reason and the trace has `net_dev_queue` headers:** this may be a per-flow TCP path problem — run `net_loss.py` and hand it to `svc_net` (blueprint 5).

**Next:** Step 4.

### Step 4. Rule out the lookalikes

| Check | Where to look | A packet-drop fault looks like this |
|---|---|---|
| Is it just a quiet period? | Step 3, baseline vs window | Drops rise while `skb_consume` / receive keep going. If everything fell together, it is a wind-down, not drops |
| Is it CPU? | `sched_budget.py` on the window slice — is `wait` high? | `wait` near zero. If `wait` is high, drops may be a symptom of CPU starvation — hand to the CPU-cap / noisy-neighbor blueprints and note it |
| Is it a one-service TCP path? | drop reasons + `net_loss.py` | Drops here are host-level with a stack reason, not TCP retransmissions on one flow. If it is TCP per-flow, use `svc_net` |
| Is it memory? | the memory blueprint's reclaim check | No memcg reclaim |

If a check does not fit, say which, and treat the verdict as unconfirmed.

**Next:** Step 5.

### Step 5. Identify where the drops land

- **Reason** is the strongest identity: it names the mechanism (`QDISC_DROP` = a queue discipline, `NETFILTER_DROP` = a firewall rule, `NO_SOCKET` = nothing listening, an `RX_*` code = the receive path).
- **Process / interface:** the owning process from `net_drops.py`, and — if these are forwarding daemons on a single-namespace host — name them and the receive path rather than a "container" (there is none to name). A `pid_ns` of 0 for every event means no per-container attribution is possible; say so.
- `victim_info.py` / `wake_graph.py` on the top owning PID give its names and who it talks to.

**Next:** Step 6.

### Step 6. Write the RCA statement

Template:

> From **[start]** to **[end]** (UTC) this host was **dropping packets**: `skb_kfree` rose to **[rate]/s** (baseline **[rate]/s**), reason **[top reason]**, on **[process / receive path]**, with a matching dip in `net_if_receive_skb` at **[time]**. We ruled out **[a quiet period / CPU / a one-service TCP path / memory]** because **[reason]**. We did not check **[what was not tested]**.

Rules:

- Give the drop rate **window vs baseline** — the baseline is what makes the number mean something.
- Quote the **reason** when the kernel records it; when it does not, say so and lean on the burst + receive-dip alignment.
- Mark each claim **Measured** (the rates, the reason, the window) or **Inferred** (why the drops happen — the trace shows the drop, rarely the upstream cause).
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one thing: the host is dropping packets. It hands off to `svc_net` (per-flow TCP loss), the CPU-cap / noisy-neighbor blueprints (drops caused by CPU starvation), or the memory blueprint when the evidence points elsewhere.
- It needs `skb_kfree`. Without it, drops are not observable in the trace.
- **Drop reasons need a recent kernel** (~5.17+). On older kernels `skb_kfree` carries no reason; the tool falls back to rate + clustering + the receive dip, which is weaker — it can miss a low, steady drop rate that a reason would have named.
- **`skb_kfree` is not only true drops.** Some frees on normal-but-unusual paths also use it. That is why the reason and the baseline comparison matter — a rise with a real reason, not the raw count, is the fault.
- **No calibration numbers yet.** Thresholds here are qualitative (shape, not size) until a labeled packet-drop run is available to read. Always compare against a baseline slice.
- It says *that* the host drops packets and *where* (reason, process, path), not always *why* upstream (which rule, which link, which peer).

---

## Part 6. References

1. Linux kernel, `kfree_skb` drop reasons (`enum skb_drop_reason`, `include/net/dropreason-core.h`); the `skb:kfree_skb` tracepoint. https://docs.kernel.org/networking/index.html
2. B. Gregg, *Systems Performance*, 2nd ed., chapter 10 (Network) — dropped packets and receive-path analysis. https://brendangregg.com/systems-performance-2nd-edition-book.html
3. Linux `tc` / qdisc documentation (queue drops). https://man7.org/linux/man-pages/man8/tc.8.html
4. LTTng documentation (the `skb` and `net_*` kernel events). https://lttng.org/docs/
5. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the index files hold

The same as the other blueprints: each channel file has an `index/*.idx` table of contents saying where each packet sits and what time it covers. `idx_summary.py` and the count-index tools read only this, which is why Steps 1 and 2 take seconds. Step 3 decodes the actual events for the one window you cut.
