# svc_cpu_cap: how to find the root cause from a kernel trace
 
|                              |                                                                                             |
|------------------------------|---------------------------------------------------------------------------------------------|
| Problem class                | Latency                                                                                     |
| Name in the dataset          | `svc_cpu_cap` (service CPU cap)                                                             |
| Evidence used by this method | The kernel trace folder: `kernel/kernel/` (`channel0_*`, `index/`, `metadata`)              |
| Also used                    | `meta/lttng_enabled_kernel.txt`, the tracer setup. Whoever records a trace knows it         |
| Not used                     | The rest of `meta/`, logs, spans, metrics                                                   |

1. What is Service CPU Cap fault?
- This fault is caused when a fault is limiting/abusing a service's resources.
- When a container is given a CPU limit that is too small for its work.

#### What the fault is
 
A container is given a CPU limit that is too small for its work.
 
Linux enforces the limit with a **quota** and a **period**. In cgroup v2 these are two numbers in the file `cpu.max`.
 
```
cpu.max = 20000 100000
```
 
This means: in every 100,000 microsecond (100 ms) period, all threads of the container together may use 20,000 microseconds (20 ms) of CPU. That equals **0.2 cores**.

What happens behind the scenes:
- The container's thread runs and uses up the quota.
- The kernel stops them. This is called *throttling*.
- They stay stopped until the next period starts and quota is refilled.

Symptoms for the throttled container:
- Long waits for the CPU. Many threads are ready but not running. Waits start appearing.
- Low/flat CPU usage.
- A BURST-AND-FREEZE behavior in the victim.
- Other processes are working normally.
- There is no disk wait.

#### What is needed for RCA using Kernel trace?
| Input                                                                                | Why                                                        |
|--------------------------------------------------------------------------------------|------------------------------------------------------------|
| The trace folder `kernel/kernel/` with `channel0_*`, `index/*.idx`                   | Everything in this method comes from here                  |
| `sched_switch` and `sched_waking` (or `sched_wakeup`) events in the trace            | To measure running, waiting, and sleeping time             |
| A baseline: a normal period in the same trace, or a fault-free trace of the same app | You judge numbers only by comparison                       |
| `babeltrace2` and `python3`                                                          | To read the trace                                          |
| The seven scripts, all in one folder                                                 | To read the index, cut slices, and compute the time budget |
 
The scripts:
 
| Script              | What it does                                                                                   |
|---------------------|------------------------------------------------------------------------------------------------|
| `idx_summary.py`    | Trace start, end, length, CPUs, packet size, lost events, health checks, data rate over time   |
| `idx_dump.py`       | Every field of one `.idx` file, one row per packet                                             |
| `idx_slice.py`      | Copies only the packets that cover a time window into a small trace                            |
| `extract_slice.sh`  | Calls `idx_slice.py`, then `babeltrace2`, and keeps only scheduling events                     |
| `sched_budget.py`   | Time budget per process: running, waiting, sleeping, long waits                                |
| `rhythm.py`         | How often a process gets the CPU, in 10 ms buckets                                             |
| `wake_graph.py`     | Which processes wake the victim, and which ones it wakes. A hint about who talks to whom       |
 
`idx_summary.py` and `idx_dump.py` import `idx_slice.py`. `extract_slice.sh` calls it. Keep all seven in the same folder.

#### Setup
The commands in this file use these variables. The values are for the worked trace. For a new trace, change them here only.
 
```bash
RUN=~/run_A                  # the run folder. The trace is inside it
TRACE=$RUN/kernel/kernel     # the trace itself: channel0_*, metadata, index/
TOOLS=~                      # the folder that holds the seven scripts
WORK=~/work                  # scratch folder for slices
DAY=2026-09-05               # date of the trace in UTC. Step 1 prints it for a new trace
mkdir -p $WORK
ls $TOOLS/{idx_summary.py,idx_dump.py,idx_slice.py,extract_slice.sh,sched_budget.py,rhythm.py,wake_graph.py}   # all seven must be listed
```

#### Procedure
Step 1: Check what was recorded. Our goal is to know which questions the trace can answer.

``` 
cd ~/run_A
head -n 100 meta/runinfo_start.txt
head -n 100 meta/top_docker-compose_carts_1_start.txt
```
These give the clock anchors and the process IDs of the cart container.

```
cat <run>/meta/lttng_enabled_kernel.txt

# list the event names that really appear in a 1 second slice
babeltrace2 --clock-gmt --begin "<YYYY-MM-DD HH:MM:SS>" --end "<YYYY-MM-DD HH:MM:SS+1>" \
  <run>/kernel/kernel 2>/dev/null \
  | grep -o ' [a-z_0-9]*: {' | sort | uniq -c | sort -rn | head -40

# is there any event that mentions throttling? (not run yet)
grep -a -i -o 'throttl[a-z_]*' <run>/kernel/kernel/metadata | sort -u
```

- From the results, We need `sched_switch` and `sched_waking` (or `sched_wakeup`) events. These are important as it helps to measure the waiting time.
- Note which other groups exist that may be useful for RCA. `block_*`, `net_*`, `tcp`, system calls etc.
- Also note which are missing – so that we can exclude them from the analysis.



Step 2: After this, we find when and who is throttling.
Our goal is to find the window and the victim process.

We will take short slices spread across the run and extract only scheduling events. Then we will compute the time budget for each slice.

```
mkdir -p ~/work
for start in <HH:MM:SS> <HH:MM:SS> <HH:MM:SS>; do       # e.g. every 30 s across the run
  bash tools/extract_slice.sh <run> <YYYY-MM-DD> $start 10 ~/work/s_$start.txt
done

for f in ~/work/s_*.txt; do
  echo "== $f"
  python3 tools/sched_budget.py "$f" 10 | head -n 6
done
```

A whole trace would cost more time depending on the size, so this above code is sampling 10s slice only – but we can change the slice size according to the actual trace size.

Once we have the output, read the table (which is sorted by waiting time). In a normal slice, nobody will be throttled. Whereas in a fault slice, the PID for the victim process will be seen jumping to the top or higher position. That PID could be a possible victim.

Once we have this slice, we need to mark the start of the window so that we know this is the start of the fault slice and the first normal slice after it will mark the end of the fault slice. (sometimes the start and end might be missing – based on when the trace was recorded, so we need to check the slices carefully to find the faulty window vs a normal window) 


Step 3: Build the time budget and compare [Validated]
Goal: show what the victim's threads were doing, before and during the fault.

`<baseline_slice.txt>` and `<fault_slice.txt>` are not scripts. They are text files of scheduling events for one time slice each. You make them with tools/extract_slice.sh. Pick the baseline slice from a quiet time before the fault, and the fault slice from inside the fault window found in Step 2.

```
bash tools/extract_slice.sh <run> <YYYY-MM-DD> <baseline_start HH:MM:SS> 10 ~/work/baseline_slice.txt
bash tools/extract_slice.sh <run> <YYYY-MM-DD> <fault_start HH:MM:SS>    10 ~/work/fault_slice.txt
```

Then compute the budget for each:

```
python3 tools/sched_budget.py <baseline_slice.txt> 10 <victim_pid>
python3 tools/sched_budget.py <fault_slice.txt>    10 <victim_pid>
```


What this gives us is a table with the following columns:

| Column                      | Meaning                                                                          |
|-----------------------------|----------------------------------------------------------------------------------|
| `run`                       | Average number of CPU cores in use                                               |
| `wait`                      | Average number of threads that were ready but had no CPU                         |
| `preempt`                   | The part of `wait` that came from being switched out while still wanting the CPU |
| `S`                         | Average number of threads asleep (waiting for an event, lock, timer, or network) |
| `D`                         | Average number of threads in disk-type sleep                                     |
| `>=1ms`, `>=10ms`, `>=50ms` | How many times a thread waited at least that long for a CPU                      |
| `max_ms`                    | The longest single wait for a CPU                                                |
 
The script reads `prev_state` of each `sched_switch`:
 
| Code        | Meaning                                                        |
|-------------|----------------------------------------------------------------|
| 0 and 256   | The thread left the CPU but still wants it (counts as waiting) |
| 1           | Sleeping (S)                                                   |
| 2           | Disk-type sleep (D)                                            |
| 16, 32, 128 | The thread is exiting                                          |
 
Codes can differ between kernels. The script prints every code it saw. Check them first.
 
Decision:
 
- `wait` and the long-wait counts jump while `run` stays low or falls: the victim is starved of CPU. Go to Step 4.
- `run` goes up and `wait` stays small: the victim is doing more work. This is not a cap.
- `D` goes up: look at disk.
- `S` goes up with low `wait`: look at locks or network.


Step 4: Look for some kind of rhythm
Goal: separate "a cap" from other kinds of CPU starvation.

```bash
python3 tools/rhythm.py <fault_slice.txt> <victim_pid> <slice_start HH:MM:SS> 1.0
```

It prints 100 lines for 1 second. Each line is a 10 ms bucket. The bar shows how many times a victim thread got the CPU in that bucket.

Read it:
 
- **Cap:** bursts of activity, then near-empty buckets, repeating at a fixed gap. The gap is the quota period. Measure it from the output. Do not assume 100 ms.
- **No beat:** the starvation is irregular. It is probably not a cap. Go to Section 7.




### Step 5. Rule out lookalikes [Partly validated]
 
Use the table in Section 7. Quick checks:
 
| Check                                                                                              | Status                                                  |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| Other processes have short waits (the host is not overloaded)                                      | Validated: no other process waited more than 8 ms       |
| Victim `D` stays near zero (not disk)                                                              | Validated                                               |
| Victim `run` fell (not more work)                                                                  | Validated                                               |
| Idle CPUs existed while the victim waited                                                          | Proposed. The current script does not measure idle time |
| Who took the CPU when the victim was switched out (`next_comm`)? Idle, or a specific busy process? | Proposed                                                |
 
### Step 6. Estimate the limit [Average validated, per period Proposed]
 
When a container is starved by a quota, its average CPU use sits near the quota.
 
- Read `run` for the victim in the fault slice. That is about the limit in cores. (Worked run: 0.19 for a real limit of 0.2.)
- Proposed: sum the victim's on-CPU time inside each period. It should sit at a flat ceiling near quota, with little change from period to period. Without a cap it would vary a lot.
### Step 7. Write the RCA statement [Validated as a template]
 
Use the template in Section 8. Mark each claim as measured or inferred.
 
## 7. How to tell it apart from similar problems
 
| Cause                            | What the kernel trace shows                                                             | Difference from a cap                       |
|----------------------------------|-----------------------------------------------------------------------------------------|---------------------------------------------|
| **CPU cap (this fault)**         | Victim waits long, `run` is low and flat, burst-and-freeze rhythm, other processes fine | The rhythm                                  |
| Host CPU overload                | Many processes wait at once, no idle CPUs, no regular beat                              | A cap hits one container only               |
| Noisy neighbor                   | Victim is switched out and `next_comm` is a busy aggressor process; waits are irregular | A cap needs no aggressor. *(Not tested)*    |
| Heavy work or garbage collection | Victim `run` goes **up**, waits stay low                                                | In a cap, `run` goes down                   |
| Slow disk                        | `D` goes up, `block_*` events, long file system calls                                   | In a cap, `D` stays near 0                  |
| Lock waiting                     | Threads sleep (`S`) in a lock call, waits for CPU stay low                              | In a cap, threads are ready, not sleeping   |
| Network delay                    | Threads sleep in network calls, waits for CPU stay low                                  | Same as above                               |
| CPU pinning (cpuset)             | Victim runs only on some `cpu_id` values while other CPUs are idle                      | A cap moves across all CPUs. *(Not tested)* |
 
## 8. The output: an RCA statement
 
Template:
 
> From **[start]** to **[end]**, **[service]** was slow because **[mechanism]**. We know because of **[evidence 1]**, **[evidence 2]**, and **[evidence 3]**. We ruled out **[other causes]** because **[reason]**.
 
Rules:
 
- Name the service, the time window, and the mechanism.
- Give at least two independent pieces of evidence.
- Mark each claim **Measured** (seen in the trace) or **Inferred** (reasoned, not seen).
- Say what you did not test.


