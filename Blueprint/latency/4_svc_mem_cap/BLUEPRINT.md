<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a memory cap on one service (svc_mem_cap), or one process that takes the host's memory (anomaly_mem)

| | |
|---|---|
| Problem class | Latency (soft limit) and failure (hard limit) |
| Root cause this blueprint confirms or rejects | One service (container) has a memory limit that is too small for its work |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. It needs `mm_vmscan_*`, `block_rq_*`, and `sched_*` events |
| Not used | Logs, request traces (spans), metrics, container settings |

**When to use this.** One service crawls or its process dies mid-work, with no warning and no error message of its own. Its threads sit in disk-type sleep (`D`). Or the service stalls and there is a broad drop in scheduling / network activity across the whole trace, because its callers fall idle.

**Status.** The memory-cap numbers were measured on runs with known limits: one squeezed run against its fault-free baseline, five repeats of the slowdown, and the kill-gap rule on 8 runs of one workload on one machine (three kills, five finishes), with no swap. The large-request verdict (`anomaly_mem`) was measured on all 304 v2 runs of both applications (17-11-2026, tool only): 16 of 16 host-memory runs, 0 of the other 288. The reclaim finding has no `VERDICT:` line; the tool prints a `VICTIM CONTAINER` line for it. Agent (20-11-2026, graph harness, gpt-6-luna): one `anomaly_mem` run confirmed; one `svc_mem_cap` run wrongly rejected (the slices were cut after the fault had ended).

## Part 1. Background

A container gets a memory limit that is too small for its work. In cgroup v2 the limit
is `memory.high` (the SOFT limit: slow down, never kill) or `memory.max` (the HARD
limit: reclaim, and kill if that fails).

What happens when the container grows past the limit:

1. The kernel **reclaims**: it takes pages away from the container. File cache goes
   first, because it can be read back from disk.
2. The container's next read of the same file must go back to disk (a **refault**). The
   same file gets read over and over, and the work crawls.
3. Under `memory.high` that is the whole story: slower and slower, but nothing dies.
4. Under `memory.max`, if reclaim cannot free enough (the memory is anonymous: heap, not
   file cache, and there is no swap), the kernel's OOM killer kills the biggest consumer.

The trace does not record the limit itself. The key event is
`mm_vmscan_memcg_reclaim_begin/end`. "memcg" means the reclaim happens because of a
CGROUP limit. When the whole MACHINE is short of memory the kernel uses different events
(`mm_vmscan_direct_reclaim_*`, and the `kswapd` kernel thread runs).

Measured on one squeezed run: 9,224 memcg reclaims by one process in 32 seconds; the
fault-free baseline had exactly zero. The victim re-read 5.4 GB for a 1 GB working set;
the baseline read 1.07 GB. The same job: 8.5 s free, 32.4 s squeezed (about 4.7x across
five repeats). A killed process exits INSIDE its own final reclaim (gap 0.02-0.37 ms on
three kills); a process that finishes under pressure exits 8-48 ms after its last
reclaim (five runs).

Two traps:
- **A heap-heavy workload reclaims but barely re-reads.** A JVM or any managed runtime
  holds its heap as anonymous pages, so under a cap it reclaims hard while disk reads
  stay LOW. Low reads with memcg reclaim is the anonymous / hard face, NOT evidence
  against a cap.
- **The cap's cascade looks like a "scenario change".** The squeezed service stalls or
  is killed, its callers fall idle, and activity drops across the whole trace. That
  collapse is the consequence of the cap. Find the container doing memcg reclaim.

Host memory pressure (`anomaly_mem`) is a different fault: one process takes the host's
memory. A consumer asks for its memory once, when it starts, in a single request of
many GB.

Problems that look similar:

- Plain slow or busy disk: reads and `D` high, but no reclaim at all. A cap always reclaims.
- Host out of memory: `mm_vmscan_direct_reclaim_*` and `kswapd` activity; processes in DIFFERENT containers stall. A cap uses memcg reclaim and hits one container.
- CPU cap: the victim is ready-but-WAITING for a CPU (`wait` high), not sleeping on disk. Hand CPU waits to the CPU-cap blueprint.
- Cold cache / first read: one pass of reads, roughly the size of the data, no reclaim, then it stops.
- A memory leak: usage grows until SOMETHING stops it. If that is the container's limit, the trace shows exactly this fault; whether the growth was a leak needs the application's history.
- Writeback storm: `writeback_*` events and WRITES dominate. A squeezed cache shows READS (refaults).

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice and keeps the events you name (default: scheduling only; this blueprint passes a memory pattern) | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> [events_regex]` |
| `mem_pressure.py` | The memory-cap check: who reclaims (container limit or host), who asked for a lot of memory, who re-reads from disk, and who died doing it. The decisive tool here | `mem_pressure.py <slice.txt> <slice_seconds> [victim_pid]` |
| `sched_budget.py` | Time budget per process: running, waiting, sleeping (`S`), disk sleep (`D`) | `sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]` |
| `victim_info.py` | Who a process is: PID, names, threads, container | `victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]` |
| `wake_graph.py` | Which processes wake the victim, and which ones it wakes | `wake_graph.py <sched_events.txt> <pid> [rows]` |

`MEMEV='sched_switch|sched_waking|sched_wakeup|mm_vmscan_|block_rq_|sched_process_|syscall_entry_mmap'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find when something changed, and write down the candidate window. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. A memory squeeze often makes the
rate RISE (refault reads generate lots of block events), but the direction is only
a hint. A cap that bites hard can also show as a broad drop: the squeezed service
stalls or is killed and its callers fall idle. Use trace_start and trace_end if
nothing stands out.

Write down: `window_start` (start of the candidate window (trace_start if nothing stands out), HH:MM:SS only (no date)), `window_end` (end of the candidate window (trace_end if nothing stands out), HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `window_found` | the rate changed for a stretch of time |  | go to `reclaim` |
| `nothing_stands_out` | nothing stands out. Set window_start = trace_start and window_end = trace_end |  | go to `reclaim` |

### Step 3. Find out whether a memory limit is biting at all, and whose. This is the decisive measurement. (`reclaim`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/m_base.txt $MEMEV
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/m_f1.txt $MEMEV
extract_slice.sh $TRACE <day> <a second time inside the window> 10 $WORK/m_f2.txt $MEMEV
mem_pressure.py $WORK/m_base.txt 10
mem_pressure.py $WORK/m_f1.txt 10
mem_pressure.py $WORK/m_f2.txt 10
```

Cut two or three slices inside the window and one before it, keeping the memory
events. mem_pressure.py prints who reclaimed (container-limit or host), who read
from disk, and which processes started or died. It prints no VERDICT line for
reclaim; read the reclaim section.
CONTAINER-LIMIT reclaim (memcg) on one container's processes, above the baseline,
is the decisive finding: a memory cap is confirmed. You do NOT need any other
signature. The `VICTIM CONTAINER = pid_ns N` line names the capped container; read
it straight off that line, not from CPU-usage correlation. Write down the victim
pid and its pid_ns. A pid_ns of 0 is not a container; if every reclaimer's pid_ns
is unreadable (0) in this slice, sample another slice where reclaim concentrates.
HOST-pressure reclaim (direct reclaim, kswapd) instead means the machine is short of
memory, not one container. Host reclaim comes in bursts. Measured on one run:
reclaim at 15, 50 and 110 s into the fault, nothing at 5, 30, 70 and 90 s. One quiet
slice does not clear the host: sample three or four slices across the window.
Memcg reclaim can be intermittent too: a subtle cap reclaims in bursts, and a hard
cap may burst once and then the victim stalls or dies. Before you say "none",
sample more slices across the window. Reclaim above baseline in any in-window slice
confirms the cap.
If the trace has no `mm_vmscan_memcg_*` events at all, reclaim itself was not
recorded: say so clearly in the report and treat any verdict as weaker.
The `VERDICT: ... LARGE MEMORY REQUEST` line that the tool also prints here belongs
to the step `consumer`. Do not decide this step on it.

Write down: `base_start` (start of a 10 s slice before the window, HH:MM:SS only (no date)), `fault_start` (start of a 10 s slice inside the window where the reclaim was seen, HH:MM:SS only (no date)), `victim_pid` (pid of the process doing memcg reclaim), `victim_ns` (the pid_ns on the `VICTIM CONTAINER` line (the capped container)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `memcg_reclaim` | CONTAINER-LIMIT reclaim (memcg) on one container's processes, above the baseline. The tool prints the VICTIM CONTAINER line | `-> VICTIM CONTAINER = pid_ns ...` | go to `face` Root cause **confirmed**. |
| `host_reclaim` | HOST-pressure reclaim (direct) instead of memcg reclaim. The machine is short of memory, not one container. A different fault; name who took the memory | `HOST-pressure reclaim (direct): ...` | go to `consumer` |
| `kswapd_only` | no memcg and no direct reclaim, but the tool prints the `kswapd active` line (a host-pressure sign). It is not proof: on a trace with no `mm_vmscan_*` events it also appears on fault-free runs (92-483 events per 30 s). The large-request check decides | `kswapd active ( ...` | go to `consumer` |
| `no_reclaim` | no memcg reclaim anywhere, also after sampling more slices across the window, and no host-pressure sign. The large-request check still runs, because it was measured alone on a slice at the start of the window (RESULTS.md) | `none. Nobody reclaimed memory here ...` | go to `consumer` |

### Step 4. Tell the slowdown face (`memory.high`) from the killing face (`memory.max`), and confirm from the scheduler what the victim's time went to. (`face`)

```
mem_pressure.py $WORK/m_f1.txt 10
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/baseline_slice.txt
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/fault_slice.txt
sched_budget.py $WORK/baseline_slice.txt 10 <victim_pid>
sched_budget.py $WORK/fault_slice.txt 10 <victim_pid>
```

Deaths (the section "Process starts and ends" of mem_pressure.py):
- A process exited INSIDE its own reclaim, within about 1 ms of it: the hard limit
  killed it. Measured on three known kills: 0.02-0.37 ms. A process that finishes
  under pressure exits 8-48 ms after its last reclaim (five known finishes).
- The same name died several times in the window: kill-and-respawn, the thrash
  pattern of a hard limit well below the service's needs.
- Reclaim and re-reads but nobody died: the soft-limit face (or a hard limit that
  reclaim is keeping up with).
Disk reads (optional, the file-cache face only): the signature is reads far past
the size of the data being worked on, together with reclaim. Squeezed (measured):
5,369 MB against a 1 GB working set while reclaiming 9,224 times. Baseline: 1,074 MB
with zero reclaim. If the victim's memory is anonymous (a JVM heap), reads stay low.
Never downgrade the diagnosis because this number is small.
sched_budget.py, the victim's row: `D` (disk-type sleep) high and `wait` for the CPU
low means the victim sleeps on refault reads, not starved of CPU. `D` is high on a
cold-cache baseline too (measured: 0.87 squeezed against 0.66 cold baseline), so it
supports the story and does not prove it.
A small re-read ratio or a kill gap you could not pin down does not make the cap
unconfirmed. Downgrade only if a competing mechanism shows: the reclaim is
host-wide, or the victim is waiting on CPU, not sleeping on memory.

Write down: `face` (soft slowdown (nobody died) or hard kill (a process exited inside its own reclaim, or kill-and-respawn)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `hard_kill` | a process of the victim container exited inside its own reclaim (within about 1 ms), or the same name died several times in the window (kill-and-respawn) |  | go to `identify` Root cause **confirmed**. |
| `soft_slowdown` | reclaim (and maybe re-reads) but nobody died. The service crawls instead of failing |  | go to `identify` Root cause **confirmed**. |
| `cpu_wait` | the victim's `wait` is high and its `D` is low. The victim's problem is the CPU |  | **Stop.** The victim waits for the CPU, it does not sleep on memory. The cap is unconfirmed. Hand the case to blueprint `1_svc_cpu_cap`. Root cause **unconfirmed**. |

### Step 5. Under host memory pressure, name who took the memory (the large-request verdict, `anomaly_mem`). (`consumer`)

```
extract_slice.sh $TRACE <day> <window_start> 30 $WORK/m_start.txt $MEMEV
mem_pressure.py $WORK/m_start.txt 30
```

Read the section `Large memory requests` and the VERDICT line that ends it. A
consumer asks for its memory ONCE, when it starts, so the slice must begin at the
start of the window. If it shows nothing, cut the 30 s before. A later slice has no
request in it.
One process with a single request of many GB is the consumer: report it by name,
pid and `pid_ns`. The bar is 4 GB in one request. Measured: 22.0-34.5 GB in one
request on the 16 host-memory runs; no request reaches 256 MB on the other 288.
The CPU time on the line is the process touching its pages. If the same program
asks again under a new pid, the line says it was restarted.
The table `Who was allocating when the host ran short` lists who SUFFERS, not who
took the memory.
On a trace with no `mm_vmscan_*` events at all, the large request still names a
consumer, but nothing in the trace then shows that the host was actually short of
memory. Say so.

Write down: `consumer` (the process on the ONE LARGE MEMORY REQUEST line (comm, pid, pid_ns) and the GB it asked for).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `large_request` | the tool reads ONE LARGE MEMORY REQUEST. Host memory pressure; the process on the line is the consumer | `VERDICT: ONE LARGE MEMORY REQUEST ...` | go to `report` Root cause **confirmed** (`anomaly_mem`). |
| `no_large_request` | the tool reads NO LARGE MEMORY REQUEST, also on the 30 s before the window | `VERDICT: NO LARGE MEMORY REQUEST ...` | **Stop.** No process asked for 4 GB or more in one request. Not a memory cap on one container. If host-pressure reclaim (direct) was seen, report host memory pressure with no consumer named. Root cause **rejected**. |

### Step 6. Describe the victim as precisely as the trace allows. (`identify`)

```
victim_info.py $WORK/fault_slice.txt 10 <victim_pid>
wake_graph.py $WORK/fault_slice.txt <victim_pid>
```

Name the process and PID always; the container namespaces if recorded (a namespace
number of 0 means "could not be read", not a real namespace); who it talks to as a
hint. The kernel trace never holds a service or container NAME.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the victim is named |  | go to `report` |

### Report

fault_type: `anomaly_mem` if the verdict is ONE LARGE MEMORY REQUEST: report host memory
pressure with the consumer (name, pid, pid_ns) and the verdict line word for word.
Otherwise `svc_mem_cap`: From [start] to [end] (UTC), [victim] was [slowed / killed] by a
container memory limit that is too small for its work. We know because of [evidence 1:
memcg reclaim counts], [evidence 2: the re-read ratio], and [evidence 3: the kill gap /
the slowdown against baseline]. We ruled out [plain disk, host pressure, CPU] because
[reason]. We did not check [what was not tested].
Commit, do not hedge. Memcg reclaim in one container above baseline is a container
memory cap on that container. Name the victim by its pid_ns (the `VICTIM CONTAINER`
line), the time window, and which face (soft slowdown or hard kill). The broad activity
collapse is the cascade and the reclaim is the cause. The reclaim alone is sufficient to
commit; the re-read ratio, the kill gap and the `D` budget strengthen it and name the face.
Mark each claim Measured or Inferred. The limit's size is always Inferred: the limit is
smaller than the victim's working set; under the hard-limit face it is smaller than the
victim's live (anonymous) memory at the moment of the kill. Do not put a number on the
limit. Say what you did not test.

## Part 4. Measured, and limits

- It confirms or rejects one cause: a cgroup memory limit on one container, in either face. It stops and says so when the evidence points at host pressure, plain disk, or the CPU.
- It needs `mm_vmscan_memcg_*` events. Without them the verdict is much weaker — only re-reading and deaths remain, and both have innocent explanations.
- On a trace with no `mm_vmscan_*` events at all (measured: every Train Ticket run), reclaim is invisible. `Large memory requests` still names a consumer (8 of 8 host-memory runs there, one request of 22.5 GB each), but nothing in the trace then shows that the host was actually short of memory. The `kswapd active` line is not proof either: it also appears on fault-free runs of that system (92-483 events per 30 s).
- **The large-request verdict, measured on all 304 v2 runs** (17-11-2026, `RESULTS.md`): 16 of 16 host-memory runs (22.0-34.5 GB in one request, 13-28 s of CPU after it in a 30 s slice), 0 of the other 288, where no request reaches 256 MB. The slice must start at the injection: a later slice has no request in it. On Train Ticket 2 to 4 `stress-ng-vm` processes make the same request within 30 s, so the consumer is restarted there; the trace does not say why.
- It cannot read the limit's value. The CPU blueprint can estimate its quota from the ceiling; there is no memory equivalent in the trace.
- Swap changes the hard-limit face: with swap, anonymous memory is reclaimable and the kill becomes a slowdown. The measured numbers here come from machines with no swap.
- The kill-gap rule (under ~1 ms = killed, 8 ms or more = finished) was measured on 8 runs of one workload on one machine. Treat the 1 ms line as a rule of thumb, not a law.
- A single death with no reclaim nearby says nothing about memory. Processes exit all the time.
- The re-read ratio needs the working-set size, or a baseline slice, to mean anything.
