# Blueprint: finding interrupt work piled on one CPU from a kernel trace

| | |
|---|---|
| Problem class | Latency (bare-metal host: a switch or router line card, a control card, any box with no containers) |
| Root cause this blueprint confirms or rejects | Network receive work (the `NET_RX` softirq) runs on **one CPU** instead of being spread, and the threads placed on that CPU — or on its hyper-thread sibling — are slowed by it |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. Best of all: **two** traces of the same box, one with the load and one without |
| Also allowed | The list of event types the trace holds (read from `metadata`); the box's own SMT pairing, read from `/sys` |
| Not used | Logs, request traces (spans), metrics, NIC counters from outside the trace |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

**When to reach for this.** The box has no containers (every event carries the same `pid_ns`, or none). Something that lives on one CPU got slow while the machine as a whole was not busy. The symptom is often application-level and slow to see — management requests that take minutes, polls that come late — and nothing in the scheduler says "starved". The question here is not "who hogs the CPU" but "did the **kernel's own network work** land on one core, and who sits on that core".

> **Honest status.** Calibrated on **one labelled pair** of traces from a telecom control card (partner case 3): the numbers in Step 3 and Step 4 come from it, and the baseline half of the pair was read as a true negative. The trace does not know which logical CPUs share a physical core; that pairing must come from the box (Step 5). Treat the thresholds as a first calibration, not a law.

---

## Part 1. Background

### 1.1 What the fault is

When a packet arrives, the network card raises a **hardware interrupt** (hardirq). The kernel does the bare minimum there and hands the real work — pulling the packet off the ring, running the protocol code, delivering it — to a **softirq**, a piece of deferred kernel work. Receive work is softirq number 3, `NET_RX`. The driver's NAPI poll loop runs inside it.

A softirq runs **on the CPU that raised it**. Under steady load the kernel moves the backlog to a per-CPU helper thread, `ksoftirqd/N` (one per CPU). That thread **cannot be re-pinned**: `ksoftirqd/0` will only ever run on CPU 0.

So the question "which CPU does the receive work" is decided by two things:

- **Where the NIC's interrupt lands.** A multi-queue NIC (RSS) has one interrupt per queue; `/proc/irq/<n>/smp_affinity_list` says which CPU each one goes to. A single-queue NIC lands everything on one CPU.
- **RPS** (receive packet steering): `/sys/class/net/<if>/queues/rx-*/rps_cpus` can spread the softirq work to other CPUs in software.

When neither is set, or set badly, **every packet is processed on one CPU**. That CPU is then busy with kernel work for a large share of each second. Two kinds of thread suffer:

1. Threads **placed on that CPU** (pinned there, or always scheduled there). They wait behind the softirq, which runs before any thread.
2. Threads on the CPU's **SMT sibling** — the other logical CPU of the same physical core. The two share the core's execution units, so a core that is half full of network work slows the sibling too, even though the sibling's own run queue looks fine.

The slowdown is not a long wait of one thread. It is a steady tax, and it shows up as application latency that is hard to pin: management requests that take minutes, periodic jobs that drift.

### 1.2 What it looks like in a kernel trace

The trace records interrupt work directly:

- `irq_softirq_entry` / `irq_softirq_exit` with `vec = 3` (`NET_RX`), each with a `cpu_id`. Summed per CPU, this is **how much of each second each CPU spent in receive work**.
- `irq_softirq_raise`: when the work was queued. The gap raise → entry is the **softirq latency**. A large p99 on one CPU means the handler was being delayed there — that CPU is saturated.
- `irq_handler_entry` / `irq_handler_exit`: the hardware interrupts, with the device name. The receive interrupt landing on one CPU is the first half of the picture.
- `sched_switch`: how much `ksoftirqd/N` ran (the backlog that did not fit inside the interrupt), and which application threads ran on that CPU.

The signature of this fault:

- **Concentration.** On an N-CPU box the fair share of `NET_RX` time is 1/N per CPU. In the fault, one CPU carries most or all of it.
- **`ksoftirqd/N` busy.** A `ksoftirqd` thread that is near the top of the CPU table was never meant to be there. On the labelled pair it used 42% of a CPU with the load and 0% without.
- **Application threads on that CPU or its sibling.** The tool names them. They are the ones that got slow.
- **The rest of the box is calm.** Other CPUs are not saturated; nothing else waits long.

The best evidence is a **pair**: the same box with and without the load. The diff shows the receive work appearing on one CPU and nowhere else.

### 1.3 Problems that look similar

| Cause | What the kernel trace shows | How it differs from RX concentration |
|---|---|---|
| **RX concentration (this fault)** | `NET_RX` time far above 1/N on one CPU, `ksoftirqd/N` busy there, app threads on that CPU or its sibling | — |
| A genuinely busy application thread on that CPU | The CPU is busy, but with a user thread; `NET_RX` on it is small | Softirq share is normal. That is a CPU-hog question: hand to the CPU-starvation / noisy-neighbor blueprints |
| An interrupt storm from one device | **hardirq** time concentrated on one CPU, from one `irq` name, while `NET_RX` is small | Name the device from the `top irq` column; the fix is that device's interrupt rate or affinity, not RX steering |
| A timer / RCU softirq surge | `TIMER` or `RCU` softirq concentrated, not `NET_RX` | Different softirq; usually a short burst. The tool says which kind is concentrated |
| Host saturation | Every CPU busy, many threads waiting | Not one CPU; hand to the saturation / noisy-neighbor blueprint |
| A thread pinned to a busy core with no RX on it | The thread waits, the CPU is busy with other threads, `NET_RX` normal | That is CPU starvation by a crowd: blueprint 8 |
| Packet drops | `skb_kfree` rises | Blueprint 7. Drops can be a symptom of a saturated RX CPU; check this family first when `ksoftirqd` is busy |

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/` | Everything comes from here |
| `irq_softirq_entry`, `irq_softirq_exit`, `irq_softirq_raise` events | The softirq time per CPU and the raise latency |
| `irq_handler_entry`, `irq_handler_exit` events | The hardware interrupts per CPU, by device |
| `sched_switch` (plus `sched_waking` or `sched_wakeup`) | `ksoftirqd/N` time, and which threads live on the hot CPU |
| A second trace of the same box **without** the load, if one exists | The strongest evidence for this family is the pair |
| The box's SMT pairing (`/sys/devices/system/cpu/cpuN/topology/thread_siblings_list`, or `lscpu -e`) | The trace does not know which CPUs share a core |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |

The scripts (the shared scheduling set; `tracelib.py` is the parser they all use and must sit in the same folder):

| Script | What it does |
|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks. Reads only the index, so it takes seconds |
| `idx_slice.py`, `extract_slice.sh` | Cut one time window into a small trace / decoded slice, keeping the events you name |
| `irq_balance.py` | **The decisive tool here:** per-CPU hardirq and softirq time by kind, raise → entry latency, `ksoftirqd/N` time, the top threads on each CPU, the concentration check, the SMT-sibling check, and the with/without-load diff |
| `thread_top.py` | Every thread's run / wait / sleep, per CPU crowd counts; `--cpu N` shows who lives on the hot CPU |
| `runq_wait.py` | For one thread: how long it waited for its CPU and who held the CPU meanwhile |
| `sched_budget.py`, `cpu_hogs.py` | The older per-process views; used here only to cross-check |

The slice pattern this blueprint uses (interrupts + scheduling):

```bash
IRQEV='sched_switch|sched_waking|sched_wakeup|irq_handler_entry|irq_handler_exit|irq_softirq_entry|irq_softirq_exit|irq_softirq_raise'
```

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first lines.

```bash
TRACE=/path/to/trace         # the folder that holds `metadata`, `index/` and the channel files
TRACE_BASE=/path/to/quiet    # OPTIONAL: the same box recorded WITHOUT the load (leave empty if none)
TOOLS=/path/to/scripts       # the folder that holds the scripts
WORK=/path/to/scratch        # an empty folder for slices and notes
IRQEV='sched_switch|sched_waking|sched_wakeup|irq_handler_entry|irq_handler_exit|irq_softirq_entry|irq_softirq_exit|irq_softirq_raise'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_slice.py,extract_slice.sh,tracelib.py,irq_balance.py,thread_top.py,runq_wait.py} > /dev/null && echo "scripts found"
```

Both lines must print OK.

- If `metadata` is missing, `TRACE` points to the wrong folder. Look one or two levels deeper (LTTng often stores the trace under `kernel/`).

---

## Part 4. Procedure

### Step 1. Check the trace and that the interrupt events exist

**Goal:** know the trace's date, span and health, and whether it can answer this question at all.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
SECS=$(awk '/^duration/ {print int($3)+2}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START SECS=$SECS"

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -E '^irq_(softirq_(entry|exit|raise)|handler_(entry|exit))$|^sched_switch$' $WORK/event_names.txt
```

Read it:

- Read the health checks (lost events, time gaps). A trace with discarded events or long gaps has holes; the tools skip waits that span a hole and say so, but note it in your report.
- If the `metadata` is not CTF 2 JSON (an older text `metadata`), the `grep` prints nothing. Then run `babeltrace2 --output-format=ctf-metadata $TRACE | grep -E 'event \{' -A2 | grep name` instead, or simply cut the slice in Step 2 and count: `grep -c irq_softirq_entry $WORK/irq.txt`.
- **If the trace has no `irq_softirq_entry`/`exit`, stop:** report "interrupt balance cannot be judged: the trace holds no softirq events". The fault is not observable in this recording.
- Without `irq_handler_*` you lose the hardirq half; the softirq check still works.

**Next:** Step 2.

### Step 2. Cut one slice over the whole span (and the quiet pair, if you have it)

**Goal:** one decoded slice with the interrupt and scheduling events. This fault is steady under load, so you need no window hunt: take the whole recording.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $TRACE_START $SECS $WORK/irq.txt "$IRQEV"

if [ -n "$TRACE_BASE" ]; then
  python3 $TOOLS/idx_summary.py $TRACE_BASE > $WORK/summary_base.txt
  DAY_B=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary_base.txt)
  START_B=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary_base.txt)
  SECS_B=$(awk '/^duration/ {print int($3)+2}' $WORK/summary_base.txt)
  bash $TOOLS/extract_slice.sh $TRACE_BASE $DAY_B $START_B $SECS_B $WORK/irq_base.txt "$IRQEV"
fi
wc -l $WORK/irq*.txt
```

A 60 s trace of a busy 6-CPU box gives a slice of a few million lines; the tools read it in well under a minute.

If the recording is long (minutes) and the load was only on for part of it, cut a slice inside the loaded stretch and one outside it instead, and treat the outside one as `irq_base.txt`.

**Next:** Step 3.

### Step 3. Measure where the interrupt work lands (the decisive step)

```bash
python3 $TOOLS/irq_balance.py $WORK/irq.txt $SECS --watch <thread names you care about, comma-separated>
```

`--watch` is optional: give the names of the latency-sensitive threads (the application's main loop, the SDK threads, a poller). The tool reports where they ran.

It prints:

1. A header with the CPUs, seconds and event counts. If the events cover only part of the span (a snapshot-style trace) it says so and uses the covered seconds for every share.
2. **Per-CPU table:** `busy%` (non-idle time), `hardirq ms` and its top device, softirq ms by kind (`NET_RX`, `NET_TX`, `TIMER`, `SCHED`, `RCU`, other), `ksoftirqd ms`, and the three threads that ran most on that CPU.
3. **Concentration:** for every kind that reaches at least 1% of a CPU, the hottest CPU and its share of that kind's total, against the fair share 1/N. It is marked **CONCENTRATED** when the hottest CPU carries at least `max(50%, 2/N)`. For `NET_RX` it also prints the raise → entry latency on the hot CPU (p50 / p99 / max).
4. The SMT line (Step 5) and the watched threads.
5. The verdict.

The verdict lines, exactly as the tool prints them:

- `VERDICT: RX CONCENTRATED ON CPU N: P% of NET_RX time (expected E%), ksoftirqd/N at K% of a CPU, cpu busy B%`
  followed by `APP THREADS ON THAT CPU/ITS SIBLING: name, name, ...` and
  `FIX: spread RX with RSS/multi-queue IRQ affinity or RPS (/sys/class/net/<if>/queues/rx-*/rps_cpus), and pin latency-sensitive threads off that core and its SMT sibling`
- `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY` — sometimes with `(but <kind> on cpu N is concentrated - see above)` when a kind other than `NET_RX` is piled up.
- `VERDICT: NO IRQ EVENTS IN SLICE - re-cut it with the irq events regex ...` — the slice was cut without the interrupt events. Go back to Step 2.

Read it:

- **RX concentrated:** the verdict names the CPU, the share, and `ksoftirqd/N`'s share of a CPU. Write them down. Check the per-CPU row: `busy%` on that CPU well above the others, `NET_RX ms` large there and near zero elsewhere. A raise → entry p99 in the milliseconds on that CPU says the handler itself was being delayed — that CPU was saturated. Go to Step 4 if you have the pair, else Step 5.
- **Spread evenly:** every kind is near its fair share, `ksoftirqd/*` are small. **This family is rejected.** Report "interrupt work is spread; not RX concentration" and **stop** — unless the trace was recorded without the load (then it is a baseline, not a verdict; get a loaded capture).
- **Another kind is concentrated** (`hardirq`, `TIMER`, `RCU`): see the lookalikes in 1.3. Name the kind and, for hardirq, the device in the `top irq` column. That is a different fault; report it and stop.

What the labelled pair looked like (partner case 3, a 6-CPU control card, fair share 17%): with the management-interface load on, **100% of `NET_RX` time was on cpu 0**, `ksoftirqd/0` used **42% of a CPU** (the engineers measured 43.4% by hand in a trace viewer), cpu 0 was 48% busy against 18–36% elsewhere, and the raise → entry p99 on cpu 0 was 2.8 ms (max 16.6 ms). The hardware receive interrupt was also 64% on cpu 0.

Write down:

```bash
HOT_CPU=<N>            # from the verdict
RX_SHARE=<P%>          # share of NET_RX time on it
KSOFT=<K%>             # ksoftirqd/N as a share of one CPU
```

**Next:** Step 4 if you have the quiet trace, otherwise Step 5.

### Step 4. The with/without-load diff (strongest evidence)

**Goal:** show that the receive work **appeared** on that CPU with the load, and was not there before.

```bash
python3 $TOOLS/irq_balance.py $WORK/irq.txt $SECS --baseline $WORK/irq_base.txt $SECS_B --watch <names>
```

After the normal output it prints a per-CPU diff, per second of each slice:

```
cpu 0: NET_RX a -> b ms/s, hardirq a -> b ms/s, ksoftirqd a -> b ms/s, busy a% -> b%
...
on cpu N, new or >= 3x busier than baseline: ksoftirqd/N 0 -> 420 ms/s, ...
```

Read it:

- **The fault:** on the hot CPU, `NET_RX` and `ksoftirqd` go from near zero to hundreds of ms per second, and `busy` jumps; every other CPU barely moves. The "new or ≥ 3x busier" line names `ksoftirqd/N` and whatever else grew on that CPU.
- **Also run the tool on the quiet slice alone** (`irq_balance.py $WORK/irq_base.txt $SECS_B`). It must say `SPREAD EVENLY`. If the quiet trace is also concentrated, the imbalance is permanent and the load only made it visible — still this fault, but say so.

On the labelled pair: cpu 0 went `NET_RX 6 -> 486 ms/s, ksoftirqd 0 -> 420 ms/s, busy 19% -> 48%`; cpus 1–5 stayed within a few ms/s; the quiet trace alone read `SPREAD EVENLY` — a true negative.

**Next:** Step 5.

### Step 5. Who sits on that CPU, and on its sibling

**Goal:** name the threads that pay for the receive work — those are the threads to move.

The trace cannot tell which logical CPUs share a physical core. Read it on the box:

```bash
# on the box, not from the trace:
cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list | sort -u   # e.g. "0-1", "2-3", "4-5"
# or:  lscpu -e
```

Then pass the pairs (space-separated pairs, comma inside a pair):

```bash
python3 $TOOLS/irq_balance.py $WORK/irq.txt $SECS --siblings "0,1 2,3 4,5" --watch <names>
```

With `--siblings` the tool names the hot CPU's sibling and the top three threads on it. Any watched thread found on the hot CPU or its sibling is flagged `SHARES THE PHYSICAL CORE WITH THE RX LOAD`. Without `--siblings` it prints `SMT pairing unknown: ...` and judges the hot CPU only.

Then look at the hot CPU's population and whether anything waits there:

```bash
python3 $TOOLS/thread_top.py $WORK/irq.txt $SECS --cpu $HOT_CPU --top 20
python3 $TOOLS/runq_wait.py  $WORK/irq.txt <a suspected victim thread name or tid>
```

Read it:

- `thread_top.py --cpu N` lists the threads that ran on the hot CPU with their run / wait / max wait. The application or SDK threads in that list — not `ksoftirqd`, `kworker`, `swapper` — are the candidates.
- `runq_wait.py` on one of them shows its waits and who held the CPU meanwhile. On this fault the occupant is `ksoftirqd/N` or the softirq itself; the waits are many and short, not one long freeze. A `STARVED BY CROWD` verdict with application threads as the occupants points to blueprint 8 instead.
- The box's cpuset / affinity settings decide who lands here. The engineers' fix in the labelled case was to **move the application and SDK threads to other cores**, away from the RX core and its sibling.

Write down the threads to name in the report.

**Next:** Step 6.

### Step 6. Rule out lookalikes

| Check | Where to look | RX concentration looks like this |
|---|---|---|
| Is one application thread simply busy on that CPU? | Step 3 per-CPU row: `NET_RX ms` vs the top thread's ms | `NET_RX` + `ksoftirqd` is the large part. If a user thread is the large part and `NET_RX` is small, it is a hog or a crowd — blueprint 8 / noisy neighbor |
| Is it an interrupt storm? | Concentration block: `hardirq` CONCENTRATED, `NET_RX` not | Both the hardirq and `NET_RX` on the same CPU, `NET_RX` the larger. hardirq alone from one device = a storm; name the device |
| Is it a timer / RCU surge? | Concentration block: `TIMER` or `RCU` concentrated | `NET_RX` is the concentrated kind |
| Is the whole box busy? | Step 3 `busy%` on every CPU | Only the hot CPU is high; the rest are moderate. If all CPUs are ≥ 90% busy, it is saturation |
| Did the load change the picture? | Step 4 diff | `NET_RX` / `ksoftirqd` appear on one CPU with the load; nothing else grows across the box |

If a check does not fit, say which, and treat the verdict as unconfirmed.

**Next:** Step 7.

### Step 7. Write the RCA statement

Template:

> From **[start]** to **[end]** (UTC), on this **[N]-CPU host**, all network receive work ran on **cpu [N]**: **[P]%** of `NET_RX` softirq time (fair share [E]%), `ksoftirqd/[N]` at **[K]%** of a CPU, cpu [N] **[B]%** busy against [x–y]% elsewhere **(Measured)**. The threads **[names]** ran on that CPU / on its SMT sibling cpu [M] and were slowed by it **(Measured placement; Inferred slowdown)**. Without the load the same CPU carried **[a]** ms/s of `NET_RX` and `ksoftirqd/[N]` did not run **(Measured, pair)**. We ruled out **[a busy user thread / an interrupt storm / saturation]** because **[reason]**. Fix: spread RX across CPUs (RSS multi-queue IRQ affinity, or RPS via `/sys/class/net/<if>/queues/rx-*/rps_cpus`), and keep the latency-sensitive threads off that core and its sibling. We did not check **[what was not tested]**.

Rules:

- Give the concentration against the fair share, and `ksoftirqd/N`'s share of a CPU — those two numbers are the finding.
- Name the threads on the hot CPU and its sibling: that is what the operator will move.
- Mark each claim **Measured** or **Inferred**. The placement is measured; the slowdown of the threads is inferred unless `runq_wait.py` showed their waits.
- Be honest about the symptom: the user-visible problem (slow management replies, late polls) is **application-level and takes minutes** to show, so a 60 s kernel trace shows the **mechanism**, not the symptom. The with/without-load diff is what makes the case convincing. Say so if you had no pair.
- Say what you did not test (for example, the SMT pairing if it was not read from the box).

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: interrupt / softirq work piled on one CPU. A hardirq storm, a timer surge or a plain CPU hog are reported as "not this" and handed on.
- It needs the softirq events. A trace recorded without `irq_softirq_*` cannot answer the question.
- **SMT pairing is not in the trace.** Without `--siblings` the tool can only judge the hot CPU itself; the sibling half of the story needs `/sys` from the box.
- It shows the mechanism, not the application symptom. A slow management reply that takes minutes is not visible in a 60 s trace; the link is inferred.
- **Calibrated on one labelled pair.** The CONCENTRATED rule (hottest CPU ≥ `max(50%, 2/N)` of a kind that reaches ≥ 1% of a CPU) read that pair correctly — 100% with the load, spread without. It has not yet seen a partial concentration (say 60% on one CPU) with ground truth; treat such cases as "likely" and lean on the pair diff.
- Snapshot-style traces hold events for only part of the span they were cut over; the tool detects that and divides by the covered seconds, and skips waits that span a hole. Read its note under the header.
- It cannot tell you which NIC queue or which `smp_affinity` setting is wrong, only which CPU ends up with the work. The device name in `top irq` is the lead.

---

## Part 6. References

How the receive path and its steering work:

1. Linux kernel documentation, *Scaling in the Linux Networking Stack* (RSS, RPS, RFS, XPS). https://docs.kernel.org/networking/scaling.html
2. A. Chaiken, *IRQs: the Hard, the Soft, the Threaded and the Preemptible*, ELCE 2016. https://events.static.linuxfound.org/sites/events/files/slides/Chaiken_ELCE2016.pdf
3. Red Hat, *Low Latency Performance Tuning for Red Hat Enterprise Linux 7* (ksoftirqd and kworker cannot be affined; bind IRQs away from the application's cores). https://access.redhat.com/sites/default/files/attachments/201501-perf-brief-low-latency-tuning-rhel7-v1.1.pdf
4. Linux kernel documentation, *CPU Isolation* (housekeeping CPUs, `irqaffinity`, `isolcpus`). https://docs.kernel.org/admin-guide/cpu-isolation.html
5. Linux kernel documentation, *How CPU topology info is exported via sysfs* (`thread_siblings_list`). https://docs.kernel.org/admin-guide/cputopology.html

The method, measuring interrupts from kernel traces:

6. LTTng analyses project: `lttng-irqstats` (hardirq and softirq durations, softirq raise latency), `lttng-cputop`. https://github.com/lttng/lttng-analyses
7. Trace Compass, *LTTng Kernel Analysis* — the Resources view (CPUs, IRQs, soft IRQs over time). https://archive.eclipse.org/tracecompass/doc/stable/org.eclipse.tracecompass.doc.user/LTTng-Kernel-Analysis.html
8. B. Gregg, *Systems Performance*, 2nd ed., chapter 6 (CPUs: interrupts, softirqs) and chapter 10 (Network). https://brendangregg.com/systems-performance-2nd-edition-book.html

The tools and the trace format:

9. LTTng documentation (the `irq_*` and `sched_*` kernel events). https://lttng.org/docs/
10. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What `irq_balance.py` measures

You do not need this to follow the steps. It explains the numbers in the table.

- **hardirq ms per CPU:** every `irq_handler_entry` on a CPU opens an interval that the next `irq_handler_exit` on the same CPU closes. Summed per CPU and per `irq` name. The `top irq` column is the device with the most time.
- **softirq ms per CPU and kind:** the same pairing for `irq_softirq_entry` / `irq_softirq_exit`, keyed by `vec` (0 HI, 1 TIMER, 2 NET_TX, 3 NET_RX, 4 BLOCK, 5 IRQ_POLL, 6 TASKLET, 7 SCHED, 8 HRTIMER, 9 RCU). A hardirq inside a softirq is counted in both; unmatched exits are ignored.
- **raise → entry latency:** an `irq_softirq_raise` of kind `vec` on a CPU is matched to the next `irq_softirq_entry` of the same kind on the same CPU. p50 / p99 / max per kind on the hot CPU. A big p99 means the softirq could not run promptly — the CPU was already full.
- **ksoftirqd ms:** the run intervals of the threads named `ksoftirqd/N` from `sched_switch`. This is the backlog that overflowed the interrupt path.
- **busy%:** the share of the slice a CPU was not running the idle task (`swapper/N`), from `sched_switch`.
- **top threads:** the three threads with the most run time on each CPU.
- **Concentration:** per kind that reaches ≥ 1% of one CPU's time, the hottest CPU's share of the kind's total versus the fair share 1/N. CONCENTRATED when ≥ `max(50%, 2/N)`.
- **Diff (`--baseline`):** the same per-CPU numbers for the quiet slice, both divided by their own seconds, printed as `a -> b ms/s`; plus the threads on the hot CPU that are new or at least 3× busier.
- **Seconds:** if the events cover less than 80% of the seconds you gave (snapshot-style trace), the covered span is used and a note is printed.

All parsing goes through `tracelib.py`, which accepts traces with or without a per-event context block, enum or numeric `prev_state`, and charges interrupt events to the thread that was on that CPU.

## Appendix B. One solved case

This is how one investigation went (partner case 3, anonymised). Read your own numbers against your own baseline, not against this story.

- **Box:** a telecom control card, 6 CPUs, 60 s traces, no lost events. Two captures: one with the management-interface load, one without.
- **Symptom:** management requests took minutes instead of seconds while the load was on. Nothing in the scheduler showed a long wait.
- **Step 3, with the load:** `VERDICT: RX CONCENTRATED ON CPU 0: 100% of NET_RX time (expected 17%), ksoftirqd/0 at 42% of a CPU, cpu busy 48%`. The hardware receive interrupt was 64% on cpu 0 too. Raise → entry p99 on cpu 0: 2.8 ms.
- **Step 4, the pair:** `cpu 0: NET_RX 6 -> 486 ms/s, ksoftirqd 0 -> 420 ms/s, busy 19% -> 48%`; the other CPUs moved by a few ms/s. The quiet capture alone: `SPREAD EVENLY`.
- **Step 5:** the SDK threads were placed on cpus 0, 1, 4 and 5, so some sat on the RX core and, with cpus 0 and 1 one physical core, on its sibling. The tool named them under `APP THREADS ON THAT CPU/ITS SIBLING`. The main application thread was on cpu 2 and unaffected.
- **Step 6:** no single user thread dominated cpu 0; no other kind was concentrated with the load; the box as a whole was 18–36% busy elsewhere.
- **The engineers' fix:** keep the application thread on its own core and move the SDK threads to cores 4 and 5, away from the RX core and its sibling. Management replies got faster.
- **Lesson:** the quiet capture is what made it certain. One trace shows a busy cpu 0; the pair shows the receive work appearing there with the load and nowhere else.
