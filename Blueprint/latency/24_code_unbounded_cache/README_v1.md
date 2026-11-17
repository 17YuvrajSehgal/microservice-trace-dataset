# Blueprint: the memory of one process only grows (a leak, or a cache with no limit)

| | |
|---|---|
| Problem class | Resource leak (a code defect) |
| Root cause this blueprint confirms or rejects | One process keeps taking memory from the kernel in every second and gives little back, while it does its normal work |
| Evidence | An LTTng kernel trace only, with the `brk`, `mmap`, `munmap` system calls and `sched_process_fork` |
| Not used | Logs, metrics, source code |

**When to use this.** Nothing is slow or failing yet. A container's memory use climbs for as
long as traffic arrives, or a service was killed for memory and nobody knows what filled it.

> **Honest status.** Calibrated on the 5 labelled `code_unbounded_cache` runs (Sock Shop
> front-end: 64 kB kept per request, never freed) and checked on all other v2 runs. Two
> rules were added after sweeps (Part 4). Tool only; the agent has not been run on it.

---

## Part 1. Background

A process gets memory with `mmap` (a new region) or `brk` (a longer heap) and returns it
with `munmap`. The tool adds these up per process and per second.

| | this fault | a healthy JVM | a JVM whose dependency is frozen |
|---|---|---|---|
| net growth in 30 s | **413-431 MB** | 17-29 MB | 312-344 MB |
| share of the seconds with growth | 100% | 90-100% | 100% |
| kept, of what it asked for | **21-22%** | 1% | 21% |
| threads started in the 30 s | **0** | few | 1,470-1,616 |

So growth alone is not enough. A garbage-collected runtime asks for and returns gigabytes
and keeps almost nothing. And a service whose requests pile up starts a thread per request,
and each thread maps a stack: its memory grows, but nothing leaks.

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `mem_growth.py` | Net memory taken per process, per second; the verdict | `mem_growth.py <slice> <secs>` |
| `victim_info.py` | Who a pid is | see blueprint 2 |

```bash
MEMSYS='syscall_exit_brk|syscall_entry_mmap|syscall_entry_munmap|sched_process_fork'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Pick a time inside the suspect window (`T`).

### Step 2. One slice of 30 s
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $T 30 $WORK/mem.txt "$MEMSYS"
```

### Step 3. The decisive check
```bash
python3 $TOOLS/mem_growth.py $WORK/mem.txt 30
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: MEMORY ONLY GROWS: <comm> (pid P, pid_ns N) took X MB more in 30 s (R MB/s), growing in 100% of the seconds, Y MB given back, 0 threads started` | **This fault.** That process leaks or caches without a limit |
| `VERDICT: MEMORY GROWS WITH NEW THREADS: <comm> ... started K threads - requests are piling up, this is not a leak` | Not this fault. Find what the process waits for (blueprint 15 for a frozen dependency) |
| `VERDICT: NO STEADY MEMORY GROWTH (largest: ...)` | Not this fault |

To see that the growth is tied to the fault, run the same check on a slice before the window.

### Step 4. Submit
- `fault_type`: `code_unbounded_cache`.
- `root_cause_service`: the process on the verdict line (`comm`, `pid`, `pid_ns`).
- `evidence`: the verdict line word for word.
- Fix: bound the cache and evict entries. The trace cannot name the data structure.

---

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **5 of 5 fault runs, 0 false alarms in 297 other runs** (final rule). The 5
  `dependency_outage` runs get the "new threads" verdict.
- **Two rules were added after sweeps.** (1) The process must keep 10% of what it asked for;
  without it one JVM fired in 97 other Sock Shop runs (17-29 MB kept of about 2 GB asked).
  (2) Growth of up to 2 MB per thread started is a pile-up; without it the 5
  `dependency_outage` runs fired. Rule (2) was applied to the saved outputs of job 2880078,
  not run again on the slices.
- **It sees what is asked from the kernel, not what is used.** Memory a runtime takes once
  and reuses inside (a JVM heap at its full size) shows no growth here even if the program
  leaks objects inside it. A JVM also returns memory by remapping it without access, which
  this tool does not count.
- **A slow leak is below the bar.** The bar is 0.5 MB/s; this defect is 14 MB/s.
- **One defect in one runtime** (Node). Not tested on a leaking Go or Java service.
