# Blueprint: a service that stopped running (dependency_outage)

| | |
|---|---|
| Problem class | Availability (a dependency is down or frozen) |
| Root cause this blueprint confirms or rejects | One container's processes **stop being scheduled at all**: paused (`docker pause`, a cgroup freezer, `SIGSTOP`), or dead. Its callers then wait on connections that never answer, time out and retry, so they slow down too |
| Evidence | An LTTng kernel trace with the container context (`pid_ns`) |
| Not used | Logs (they would show the timeouts), request traces (they would point at the callee) |

**When to use this.** Requests fail or time out; several services slow at once; nothing burns
CPU, disk or network. The question is: **who went quiet?**

> **Honest status (updated 17-11-2026).** Calibrated on the 5 labelled Sock Shop v2
> `dependency_outage` runs (`payment` paused with `docker pause` for 120 s). It also covers
> `queue_backlog` (the queue consumer paused the same way). Checked on all 304 v2 runs of both
> applications: the two steps together find 15 of 15 frozen containers with 0 false alarms.
> **Step 3 alone is not enough**: silence alone fires on 80 other runs (Part 4), so Step 3b
> is required.

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
| `freeze_moment.py` | Confirms a freeze: every thread of the namespace scheduled out at one moment | `freeze_moment.py <sched_slice> <secs> [--ns PID_NS]` |
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

### Step 3b. Confirm the freeze (required)
Silence is not proof. A service with no traffic is silent, and so is a helper that ended.
A freeze has a moment: the kernel makes every thread of the container run once so that it
can park itself, also the threads that had been asleep. Cut one scheduling slice that starts
at the baseline slice and ends after the fault slice, so it contains that moment:
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START <secs from BASE_START to the end of the fault slice>      $WORK/s.txt 'sched_switch|sched_process_exit'
python3 $TOOLS/freeze_moment.py $WORK/s.txt <secs> --ns <ns from the Step 3 verdict>
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: FROZEN AT hh:mm:ss: ns N (<comm>): K of its T threads were scheduled out within X ms (D of them had been asleep for 1 s or more) and none ran again ...` | **Confirmed.** The time is the start of the incident window |
| `VERDICT: EXITED AT ...: ... thread exits in its last second` | It ended or was killed (for example by the memory limit). Not a freeze; say "crashed" |
| `VERDICT: NO FREEZE MOMENT (...)` | The namespace only went idle. **Not this fault**; drop the Step 3 verdict |

### Step 4. Submit
- `fault_type`: `dependency_outage` if other services call the frozen container; `queue_backlog`
  if it is a queue consumer (nobody waits for it, work piles up in the broker). The trace
  names the container; which of the two it is depends on what that container does.
- `root_cause_service`: the silent container (its name, or comm + pid_ns).
- `culprit_kind`: `container`; `victim_thread`: `none`; list the affected callers in `evidence`.
- `incident_window`: from the drop to where the namespace's events return (or the end).
- `evidence`: the verdict line and the affected list.
- Fix: unpause / restart it; then find out who paused it or why it stopped.

---

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- **Full check, 17-11-2026 (all 304 runs).** `ns_silence.py` finds the frozen container in
  15 of 15 runs (`dependency_outage` on both applications, `queue_backlog`). It also reports a
  frozen service on 80 other runs: 12 on Sock Shop and 68 on Train Ticket (idle `openresty`
  and `toxiproxy`, helper processes that ended between the two slices, traffic that
  collapsed). `freeze_moment.py` on the named namespace keeps the 15 (19-143 threads within
  0.1-1.7 ms, 13-133 of them woken from sleep), calls 5 "exited" and rejects 75.
- **`freeze_moment.py` must be given the namespace from Step 3.** Run on every namespace it
  still calls an idle `toxiproxy` frozen in 3 Train Ticket runs (7 threads, 3-4 woken from
  sleep): a small Go program wakes all its threads now and then by itself.
- **The trace cannot tell `queue_backlog` from `dependency_outage`.** Accepted connections do
  not help (0-1 in 10 s for both; connections are kept open).
- Needs the container context (`pid_ns`). On a bare-metal box, run it per process name instead
  (not built yet).
- A service that idles legitimately (no traffic at all) can look silent; the bar (>= 20
  events/s before) keeps quiet services out.
