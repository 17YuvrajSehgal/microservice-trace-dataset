# Blueprint: a service that stopped running (dependency_outage)

| | |
|---|---|
| Problem class | Availability (a dependency is down or frozen) |
| Root cause this blueprint confirms or rejects | One container's processes **stop being scheduled at all**: paused (`docker pause`, a cgroup freezer, `SIGSTOP`), or dead. Its callers then wait on connections that never answer, time out and retry, so they slow down too |
| Evidence | An LTTng kernel trace with the container context (`pid_ns`) |
| Not used | Logs (they would show the timeouts), request traces (they would point at the callee) |

**When to use this.** Requests fail or time out; several services slow at once; nothing burns
CPU, disk or network. The question is: **who went quiet?**

> **Honest status.** Calibrated on the 5 labelled Sock Shop v2 `dependency_outage` runs
> (`payment` paused with `docker pause` for 120 s) and checked against 15 runs of other faults
> and 3 normal runs.

---

## Part 1. Background

Every running thread produces kernel events (it is scheduled in and out, it makes system calls).
A **paused** container's threads are never scheduled, so **no event at all carries its
namespace**. That silence is the signature: measured on run r1, the paused `payment` service
went from 3,441 events in 10 s to **exactly 0**, while its callers fell to about half.

The tool also tells "paused" from "died": a dead container shows `sched_process_exit` events
first (and, if it restarts, new `exec`s).

| Lookalike | What the trace shows | How it differs |
|---|---|---|
| **frozen / paused service (this)** | one namespace drops to 0 events, no exits | — |
| a crash | the namespace's processes exit (`sched_process_exit`), maybe restart | exits present - the tool says SERVICE GONE |
| fd_exhaustion (`12`) | EMFILE, then a restart loop | errors and restarts, not silence |
| deadlock (`14`) | the process still produces events; some threads stuck in futex | not silent |
| slow dependency (`3`) | the callee is busy and answers late | the callee is active, not silent |
| a service with no traffic | low rate before and after | the bar needs >= 20 events/s before |

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `ns_silence.py` | Events per second per namespace, baseline vs fault; exits, forks, execs; the verdict | `ns_silence.py <base> <secs> <fault> <secs>` |
| `sched_budget.py` | The callers' sleep and wait (who is affected) | `sched_budget.py <slice> <secs>` |

```bash
SEV='sched_switch|sched_waking|sched_wakeup|sched_process_|syscall_'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
`WINDOW_START` = where the rate drops and stays down.

### Step 2. A quiet baseline and a slice inside the drop
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/b.txt "$SEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/f.txt "$SEV"
```
Start the fault slice a few seconds **after** the drop, so it lies fully inside the outage.

### Step 3. The decisive check
```bash
python3 $TOOLS/ns_silence.py $WORK/b.txt 10 $WORK/f.txt 10
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: SERVICE FROZEN: ns N (<comm>) went from R/s to 0 events/s with no process exit ...; affected: ...` | **This fault**: a paused / stopped dependency. The `affected` list are its callers |
| `VERDICT: SERVICE GONE: ... X of its processes exited` | the dependency died (and maybe restarted): still `dependency_outage`, say "crashed" |
| `NO SILENT SERVICE (...)` | Not this fault |

### Step 4. Submit
- `fault_type`: `dependency_outage`.
- `root_cause_service`: the silent container (its name, or comm + pid_ns).
- `culprit_kind`: `container`; `victim_thread`: `none`; list the affected callers in `evidence`.
- `incident_window`: from the drop to where the namespace's events return (or the end).
- `evidence`: the verdict line and the affected list.
- Fix: unpause / restart it; then find out who paused it or why it stopped.

---

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- Needs the container context (`pid_ns`). On a bare-metal box, run it per process name instead
  (not built yet).
- A service that idles legitimately (no traffic at all) can look silent; the bar (>= 20
  events/s before) keeps quiet services out.
