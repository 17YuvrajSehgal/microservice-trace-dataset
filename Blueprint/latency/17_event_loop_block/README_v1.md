# Blueprint: a service thread that computes and stops serving (event_loop_block)

| | |
|---|---|
| Problem class | Code defect in one service (single-threaded runtime) |
| Root cause this blueprint confirms or rejects | A request-serving thread - a Node.js event loop is the usual case - does **synchronous CPU work inside a request handler**: a hash, a busy wait, a tight loop. While it computes it cannot accept, read or answer anything, so the whole service stalls, including requests that never touch that code |
| Evidence | An LTTng kernel trace only: `metadata`, the channel files, `index/` |
| Not used | Logs, metrics, request traces. (Callers' logs show timeouts; the service itself usually logs nothing) |

**When to use this.** A service stopped answering but is not down: its process is alive and
**its CPU use looks the same as before**. Callers time out or hit their own limits. The host's
total event rate **drops** (less network, fewer system calls) with no resource saturated.

> **Honest status.** Calibrated on the 10 labelled Sock Shop v2 runs of the two code defects that
> have a runtime effect (`code_event_loop_block`, `code_serial_awaits`, 5 each; both in the
> front-end Node service) and checked against 47 runs of other faults and normal load. See Part 4.

---

## Part 1. Background

A healthy serving thread alternates: a little CPU, then a system call (`read`, `write`,
`epoll_wait`, `futex`), thousands of times per second. The CPU time between two system calls is
a **syscall-free run**. It is normally far below a millisecond.

A blocked loop stays on a CPU for tens or hundreds of milliseconds without entering the kernel
once. That is the whole signature, and **CPU tables cannot see it**:

| front-end Node main thread (measured, run r1) | before | during |
|---|---|---|
| CPU use | 95% | 98% |
| system calls per second | 6,755 | 243 |
| share of time in syscall-free runs of >= 20 ms | 0.0% | 95% |
| a typical such run | none | 107 ms |

The thread was busy before and is busy now. What changed is that it stopped talking to the kernel.

| Lookalike | What the trace shows | How it differs |
|---|---|---|
| **blocked loop (this)** | a thread that made thousands of system calls per second now makes few, and computes in long runs | the SAME thread (same tid) existed before and served |
| noisy neighbour / CPU anomaly (`2`) | `stress-ng-cpu` threads compute without system calls | a NEW process; nothing that used to serve has stopped. The tool prints a NOTE, not a verdict |
| CPU cap (`1`) | the service is throttled | its threads are OFF the CPU waiting for quota; no long runs (measured: 0-6%) |
| lock contention (`11`, lock family) | threads sleep in `futex` | sleeping, not computing |
| dependency outage (`15`) | a container goes silent | its threads are asleep or gone; here the thread is at ~100% CPU |

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `loop_block.py` | Per thread: CPU share, system calls per second, time in long syscall-free runs, against a baseline; the verdict | `loop_block.py <slice> <secs> --baseline <base> <secs>` |
| `sched_budget.py` | Who waited for CPU meanwhile (to rule out a starved host) | `sched_budget.py <slice> <secs>` |

```bash
LEV='sched_switch|syscall_entry_'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Write down `DAY`, the span, and where the event rate **falls** (`WINDOW_START`). A blocked
front door makes the whole host quieter: on run r1 the host's scheduling and system-call events
fell about 8x (1.6 million lines in the 5 s baseline slice, 0.21 million in the fault slice).
If the rate never changes, pick the middle of the recording and a slice near its start.

### Step 2. A fault slice and a baseline (5 s each)
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 5 $WORK/lf.txt "$LEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   5 $WORK/lb.txt "$LEV"
```
`WINDOW_START` here = a time 30-60 s after the change, so the slice is fully inside it.
`BASE_START` = a stretch before the change. **The baseline is required**: a thread that computes
without system calls is only a fault if it used to serve. Keep the slices at 5 s; the healthy
one holds every system call on the host (about 1.6 million lines).

### Step 3. The decisive check
```bash
python3 $TOOLS/loop_block.py $WORK/lf.txt 5 --baseline $WORK/lb.txt 5
```

| Line | Meaning |
|---|---|
| `VERDICT: BLOCKED LOOP: <comm> tid T pid P (ns N) spends X% of the slice computing in K runs of >= 20 ms with no system call (median M ms ...) ... system calls fell from A/s to B/s` | **This fault.** That thread is the culprit; the container of `ns N` is the service |
| `SHAPE: R long runs per second, median M ms -> ...` | Which of the two defects it looks like (below) |
| `NOTE: <comm> ... did not exist in the baseline: a new CPU-bound process` | A CPU hog, not this fault. Go to blueprint `2` |
| `NO BLOCKED LOOP: ...` | Not this fault. Stop; report the line word for word |

**Reading SHAPE.** Median run of ~100 ms, few per second: one long synchronous computation per
request (`event_loop_block`). Median of a few tens of ms, many per second: short equal busy
stretches repeated per request (`serial_work`). The 60 ms line between them comes from two
injected defects; report the numbers along with the label.

### Step 4. Rule out a starved host (one call, optional)
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 5 $WORK/sched.txt
python3 $TOOLS/sched_budget.py $WORK/sched.txt 5
```
The blocked thread should show `run` near 1.0 and little `wait`: it has a CPU and keeps it.
Large `wait` across many services is CPU pressure, a different fault.

### Step 5. Submit
- `fault_type`: `event_loop_block` or `serial_work`, as the SHAPE line says.
- `root_cause_service`: the container of the verdict's namespace (name, or `comm` + pid_ns).
- `culprit_kind`: `thread`; `culprit_thread`: `<comm> tid T`; `victim_thread`: `none`, or the
  callers that time out.
- `incident_window`: from where the event rate fell to where it recovers (Step 1).
- `evidence`: the verdict line, with the baseline numbers.
- If the source is connected: look in that service for synchronous CPU work on a path every
  request takes - a `*Sync` call, a hashing or compression call, a `while` loop on the clock - and
  put it in `culprit_code`.
- Fix: move the computation off the serving thread (async API, worker thread), or remove the wait.

---

## Part 4. Measured, and limits

- 10 / 10 labelled runs fire; 47 / 47 other runs stay quiet. Per-run lines: `RESULTS.md`.
- Margins: the fault runs spend 70-96% of the slice in long runs; the highest quiet service
  thread is 6% (a MongoDB connection thread under a CPU cap). The bar is 40%.
- Three other code defects (`code_lock_across_io`, `code_n_plus_one`, `code_unbounded_cache`)
  stay quiet here, correctly: they change nothing measurable in those runs.
- Only Node.js is covered by data. The check is per thread, so a blocked worker in a
  multi-threaded service would be found on that thread, but the service would keep answering on
  its others and the host would not go quiet. That case is not tested.
- A thread that legitimately computes for long stretches from the start (batch work, a compiler)
  gets a NOTE: it was the same in the baseline.
- A fault already active at the start of the recording has no baseline; the tool then says only
  NOTE.
