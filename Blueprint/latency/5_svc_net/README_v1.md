# Blueprint: finding a degraded network path of one service from a kernel trace

| | |
|---|---|
| Problem class | Latency |
| Root cause this blueprint confirms or rejects | ONE service's network path is degraded — its packets are delayed or dropped on the way in or out |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder |
| Also allowed | The list of event types the trace holds (read from `metadata`), and the event rules you turned on when you recorded the trace, if you know them |
| Not used | Logs, request traces (spans), metrics, container settings |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

---

## Part 1. Background

### 1.1 What the fault is

One service's network path goes bad. The machine's network is fine, the other services talk normally — but packets to or from this one container are being **dropped**, **delayed**, or both. Causes in real systems: a bad traffic-shaping rule on the container's interface, a broken overlay tunnel, a flaky virtual link, a mis-set firewall or rate limit.

TCP hides this from every log and every application error counter. When a packet is lost, TCP silently sends it again — a **retransmission** — and waits. When the path is slow, TCP just waits longer. The application sees nothing but time passing. That is why this fault has no error message anywhere, and why the kernel trace is the right place to look: **the kernel records every packet it sends, with its TCP sequence number.** A segment sent twice with the same sequence number is a retransmission, and retransmissions concentrate exactly on the broken path.

Two effects, usually together:

1. **Retransmissions** on the victim's flows — in both directions, because the victim's lost replies also make its peers resend.
2. **Throughput collapse.** Waiting on timeouts and a delayed path means far fewer requests complete. The victim's flows shrink to a trickle, and every service that calls the victim slows down with it.

### 1.2 What it looks like in a kernel trace

Measured on a run where one container (a Java service) had 150 ms delay, 40 ms jitter, and 4% packet loss put on its interface, against the same system healthy:

- **Healthy: retransmission is almost exactly zero.** 4 retransmitted segments out of 90,107 (0.0%). This is the normal background.
- **Degraded: the retransmitting flows are all the victim's.** Every flow with retransmissions touched the victim's address — its talks with its database, in both directions, at 1.4–3.2% per flow — while every other service's flows stayed at 0%.
- **The victim's traffic collapses.** Total data segments fell from 90,107 to 30,988 per 10 s. The victim's database flow fell from 1,173 segments per 10 s to about 60 — twenty times less. The whole application slowed, because the victim is on the request path.
- **The rest of the machine is healthy.** No CPU waits, no disk waits, no reclaim. The victim's own threads mostly SLEEP (`S`), waiting on sockets.

One trap, measured the hard way: **a packet crossing from a container to the host fires the transmit event once per network device** (the container's `eth0`, then the host-side bridge port). Counted naively, every segment looks sent twice — a fake "50% retransmission" on every healthy flow. The tool below counts each flow at ONE observation point, so the healthy baseline reads 0%, as it should.

### 1.3 Problems that look similar

| Cause | What the kernel trace shows | How it differs from a degraded path |
|---|---|---|
| **Degraded path of one service (this fault)** | Retransmissions concentrated on one container's flows, both directions; its throughput collapses; everyone else's flows clean | — |
| Host-wide network problem | Flows of MANY unrelated containers retransmit | One service's path hits one container's flows only |
| Slow dependency (no loss) | The victim's callers sleep (`S`) on sockets, but **zero retransmission** anywhere | Loss always leaves retransmissions. No retransmissions = the peer is slow, not the path lossy |
| The peer is CPU-capped or overloaded | The slow service shows CPU waits (`wait`) or a quota ceiling; flows are clean | Hand it to the CPU-cap or noisy-neighbor blueprint |
| The peer is memory-squeezed | memcg reclaim and disk re-reads on the peer; flows are clean | Hand it to the memory-cap blueprint |
| Connection failures (pool/fd exhaustion) | New connections fail outright; existing flows are clean | A degraded path degrades EXISTING flows |
| Pure added delay, no loss | Throughput collapses and callers sleep, but retransmission stays near zero | Possible and real: retransmission proves loss, its absence does not prove the path is clean. Say "delay suspected, loss not shown" |

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/` | Everything comes from here |
| `net_dev_queue` events **with protocol headers** (LTTng records the IP and TCP header fields) | The retransmission count comes from TCP sequence numbers |
| `sched_*` events | To show the victim and its callers sleeping on sockets |
| A normal period to compare with: a normal stretch in the same trace, or a fault-free trace of the same system | The healthy baseline is what makes 2% meaningful |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |
| The eleven scripts below, all in one folder | To read the index, cut slices, and measure |

The scripts:

| Script | What it does |
|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it takes seconds |
| `idx_dump.py` | Every field of one index file, one row per packet |
| `idx_slice.py` | Copies only the packets that cover a time window into a small trace |
| `extract_slice.sh` | Cuts one time slice and keeps the events you name (default: scheduling only; this blueprint passes a network pattern) |
| `net_loss.py` | The decisive tool here: retransmissions per flow and per sending container, counted at one observation point, plus packet frees |
| `sched_budget.py` | Time budget per process: running, waiting, sleeping (`S`), disk sleep (`D`) |
| `victim_info.py` | Who a process is: PID, names, threads, container |
| `wake_graph.py` | Which processes wake the victim, and which ones it wakes — who talks to whom |
| `cpu_hogs.py`, `rhythm.py`, `cpu_ceiling.py` | CPU checks; used here only to hand a CPU case to the right blueprint |

The slice pattern this blueprint uses (scheduling + transmits + packet frees):

```bash
NETEV='sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'
```

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the eleven scripts
WORK=/path/to/scratch      # an empty folder for slices and notes
NETEV='sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_dump.py,idx_slice.py,extract_slice.sh,net_loss.py,sched_budget.py,victim_info.py,wake_graph.py,cpu_hogs.py,rhythm.py,cpu_ceiling.py} > /dev/null && echo "all eleven scripts found"
```

Both lines must print OK.

---

## Part 4. Procedure

### Step 1. Check the trace

Same first moves as the other blueprints: `idx_summary.py` for dates and health, then the event list.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
TRACE_END=$(awk '/^trace end/ {print substr($4,1,8)}' $WORK/summary.txt)

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -c net_dev_queue $WORK/event_names.txt
```

- Read the health checks (lost events, gaps). Avoid stretches with loss, or say so.
- If the trace has **no `net_dev_queue`**, this blueprint cannot count retransmissions. Only the indirect signs remain (callers sleeping, throughput collapse) — say clearly that loss could not be measured, and treat any verdict as weaker.
- Some traces record `net_dev_queue` **without** the protocol headers. `net_loss.py` will then find no TCP segments and say so — same weakening.

**Next:** Step 2.

### Step 2. Find when something changed

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```

A degraded path usually makes the rate **fall** — requests are stuck, less work happens, fewer events. Write down the candidate window:

```bash
WINDOW_START=<HH:MM:SS>   # or TRACE_START if nothing stands out
WINDOW_END=<HH:MM:SS>     # or TRACE_END
```

**Next:** Step 3.

### Step 3. Map the retransmissions

**Goal:** find out whether any path is lossy, and whose. This is the decisive measurement — run it before anything else.

Cut one baseline slice and two or three inside the window, keeping the network events:

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY <baseline_t> 10 $WORK/n_base.txt "$NETEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY <fault_t1>   10 $WORK/n_f1.txt   "$NETEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY <fault_t2>   10 $WORK/n_f2.txt   "$NETEV"

python3 $TOOLS/net_loss.py $WORK/n_base.txt 10
python3 $TOOLS/net_loss.py $WORK/n_f1.txt   10
python3 $TOOLS/net_loss.py $WORK/n_f2.txt   10
```

`net_loss.py` prints the overall retransmission rate, the worst flows with their senders and containers (`net_ns`), and a per-container summary.

Read it:

- **Healthy looks like zero.** Measured baseline: 4 retransmits in 90,107 segments. A few scattered retransmits are normal background.
- **One container's flows retransmit, in BOTH directions, while everyone else sits at 0:** that container's path is degraded. The rate per flow does not need to be large — 1–3% per flow against a zero baseline is loud. Write down the container (`net_ns`) and its addresses. Go to Step 4.
- **Flows of many unrelated containers retransmit:** the problem is host-wide (the machine's own link or a shared bridge), not one service's path. Report that and **stop**.
- **No retransmission anywhere, in any slice:** no loss is visible. If a service is still slow and its callers sleep on sockets (check in Step 5), the path may be adding pure DELAY, or the peer may simply be slow — report "no loss shown; slow peer or added delay cannot be separated from the trace alone" and **stop** after Step 5's check.

```bash
VICTIM_NS=<net_ns>        # the container whose flows retransmit
VICTIM_IP=<a.b.c.d>       # its address, from the flow lines
BASE_START=<HH:MM:SS>
FAULT_START=<HH:MM:SS>
```

**Next:** Step 4.

### Step 4. Measure the collapse

**Goal:** show what the degraded path did to the victim's traffic. Compare the same flows in the baseline and fault outputs of Step 3:

- **Segments per flow.** Measured: the victim's database flow fell from 1,173 segments per 10 s to about 60 — twenty times less.
- **Total segments.** Measured: 90,107 → 30,988 per 10 s, because the victim sits on the request path and everything behind it starved.
- If the victim's flows did NOT shrink, the loss is real but mild — say "degraded but keeping up".

**Next:** Step 5.

### Step 5. Confirm from the scheduler side

**Goal:** a second, independent view: the victim and its callers should be SLEEPING on sockets, not computing.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START  10 $WORK/baseline_slice.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $FAULT_START 10 $WORK/fault_slice.txt
python3 $TOOLS/sched_budget.py $WORK/fault_slice.txt 10
python3 $TOOLS/sched_budget.py $WORK/baseline_slice.txt 10
```

Read it:

- The victim's processes and its callers show high `S` (sleep) and LOW `run` in the fault slice — everyone is waiting for the network. `wait` (CPU) and `D` (disk) stay near zero.
- **If instead `wait` is high:** the "network problem" is actually a CPU problem on the victim — hand the case to the CPU-cap / noisy-neighbor blueprints and **stop**.
- **If `D` is high:** look at the disk/memory blueprints instead and **stop**.
- `wake_graph.py` on a caller shows who it talks to — useful to confirm the sleepers are the victim's callers and not unrelated.

**Next:** Step 6.

### Step 6. Rule out lookalikes

| Check | Where to look | A degraded path looks like this |
|---|---|---|
| Is it host-wide? | Step 3, the per-container summary | Only the victim's container retransmits. Everyone else at ~0% |
| Is the peer just slow (no loss)? | Step 3 | Retransmissions present. Zero retransmissions = do not claim loss |
| Is it the victim's CPU? | Step 5, `wait` | Near zero. The victim sleeps, it does not queue for a CPU |
| Is it disk or memory? | Step 5, `D`; the memory blueprint's reclaim check | Near zero, no reclaim |
| Did traffic simply stop? | Step 4 against Step 3 | Collapsed traffic WITH retransmissions. Traffic that just ends (load stopped) retransmits nothing |

If one check does not fit, say which one in your report, and treat the verdict as unconfirmed.

**Next:** Step 7.

### Step 7. Say what you can about the degradation

- **Loss:** the per-flow retransmission rates are your measurement of it. Quote them per direction. The configured loss (if any was set) is not readable from the trace; your measured rate is a floor, not the exact setting — retransmission also rises from jitter and reordering.
- **Delay:** the trace shows its consequences (collapse, sleeping callers), not the delay itself. Mark delay as **Inferred** when collapse is far larger than the loss rate explains — measured here: 4% configured loss, but a 20x throughput collapse, which only the added round-trip delay explains.
- **Direction:** if only the flows OUT of the victim retransmit, the damage is on its egress; both directions usually means the path itself (its interface or link).

**Next:** Step 8.

### Step 8. Identify the victim

```bash
python3 $TOOLS/victim_info.py $WORK/fault_slice.txt 10 <victim_pid>
python3 $TOOLS/wake_graph.py  $WORK/fault_slice.txt <victim_pid>
```

Pick `<victim_pid>` from Step 3's sender column (the victim's own processes). Same honesty rules as the other blueprints: process name and PID always; the container namespaces if recorded (a 0 means "could not be read"); the addresses and ports from Step 3 are part of the identity here — "the container at `172.x.y.z` whose flows to its database at `:27017` retransmit" is concrete and checkable.

**Next:** Step 9.

### Step 9. Write the RCA statement

Template:

> From **[start]** to **[end]** (UTC), **[victim container, as named in Step 8]** was slow because its network path was degraded. We know because **[evidence 1: its flows' retransmission rates against the zero baseline]**, **[evidence 2: its throughput collapse]**, and **[evidence 3: its callers sleeping on sockets while CPU and disk stayed clean]**. We ruled out **[host-wide network, CPU, disk/memory]** because **[reason]**. We did not check **[what was not tested]**.

Rules:

- Name the victim, the window, the flows, and the measured rates.
- Give at least two independent pieces of evidence: the retransmission map (Step 3), the collapse (Step 4), the scheduler view (Step 5).
- Mark each claim **Measured** or **Inferred**. Added delay is always **Inferred** (Step 7).
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: a degraded network path of one service. It stops and says so when the evidence points at host-wide trouble, the CPU, the disk, or a merely slow peer.
- It needs `net_dev_queue` events **with protocol headers**. Without them, loss cannot be measured — only inferred from sleeping callers, which a slow peer also explains.
- **Pure delay with zero loss leaves no retransmission.** This blueprint can then only say "collapse without a local cause"; it cannot prove the path added delay.
- A packet crossing container-to-host fires the transmit event once per device. Counting naively reads as a fake 50% retransmission on every flow — measured on a healthy baseline. `net_loss.py` counts each flow at one observation point for exactly this reason.
- The measured rates (0% healthy; 1.4–3.2% per flow under 4% configured loss with 150 ms delay) come from one system. Use them as a feel for the sizes, not as thresholds; always compare against your own baseline slice.
- UDP loss leaves no retransmission at all. This blueprint is about TCP traffic.
- It cannot say WHY the path is degraded (a shaping rule, a bad link, a tunnel) — only that it is, and whose it is.

---

## Part 6. References

How TCP hides loss, and what retransmission means:

1. W. R. Stevens, *TCP/IP Illustrated, Volume 1*, 2nd ed. (retransmission, timeouts, fast retransmit).
2. Linux kernel documentation, *TCP protocol* (`tcp(7)`): https://man7.org/linux/man-pages/man7/tcp.7.html

Traffic shaping, the usual culprit behind a one-container degraded path:

3. Linux `tc-netem` manual (delay, jitter, loss on one interface). https://man7.org/linux/man-pages/man8/tc-netem.8.html

The method, reading waits and packets from kernel traces:

4. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016. https://publications.polymtl.ca/3078/
5. B. Gregg, *Systems Performance*, 2nd ed., chapter 10 (Network). https://brendangregg.com/systems-performance-2nd-edition-book.html

The tools and the trace format:

6. LTTng documentation (the `net_dev_queue` event records dissected protocol headers). https://lttng.org/docs/
7. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the index files hold

The same as the CPU-cap blueprint's Appendix A: each channel file has an `index/*.idx` table of contents saying where each packet sits and what time it covers. `idx_summary.py` reads only this, which is why Steps 1 and 2 take seconds.

## Appendix B. One solved case

How the numbers looked on a run with a known fault: 150 ms delay, 40 ms jitter, and 4% loss on one Java service's interface, injected for 2 minutes in a 4-minute trace. Use the numbers to get a feel for the sizes. Do not reuse them as thresholds.

- **Step 1:** 12 CPUs, no lost events, `net_dev_queue` with full headers present.
- **Step 2:** the data rate fell for the injection window and recovered after.
- **Step 3, baseline:** 90,107 data segments, 4 retransmitted — 0.0%.
- **Step 3, fault:** every retransmitting flow touched the victim: its talks with its database at 1.4–3.2% per flow, in both directions, while every other container's flows stayed at 0%.
- **Step 4:** the victim's database flow fell from 1,173 segments per 10 s to about 60; totals fell from 90k to 31k.
- **Step 7:** measured loss 1.4–3.2% per flow against 4% configured; the 20x collapse pointed at the added delay, which the trace cannot show directly — reported as Inferred.
- **Check afterwards:** the real injection matched — netem on that container's interface, 150 ms ± 40 ms, 4% loss.
