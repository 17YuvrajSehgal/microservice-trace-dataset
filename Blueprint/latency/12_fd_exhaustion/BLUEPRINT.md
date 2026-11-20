<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a service that ran out of file descriptors (fd_exhaustion)

| | |
|---|---|
| Problem class | Resource limit (per-process) |
| Root cause this blueprint confirms or rejects | One service's process hit its open-file limit (`RLIMIT_NOFILE`). Every call that needs a new descriptor (`accept4` for an incoming connection, `socket` for an outgoing one, `openat`, `pipe2`, `epoll_create1`) fails with EMFILE (`ret = -24`). The service then drops or refuses requests, and a Node/Go service usually crashes and restarts on the first EMFILE in `accept`, so the symptom is a restart loop. |
| Evidence | An LTTng kernel trace only: `metadata`, the channel files, `index/` |
| Not used | Logs ("EMFILE: too many open files"), container_file_descriptors metrics, application counters |

**When to use this.** The selector saw EMFILE/ENFILE returns, or a service restarting repeatedly, or an operator reports "connections refused / too many open files" on one service.

**Status.** Calibrated on one labelled Sock Shop v2 run (`fd_exhaustion_aggressive_steady_r1`: the front-end's `RLIMIT_NOFILE` lowered to just above its idle use for 120 s). Measured: 23 EMFILE returns by `node` on `accept4`/`socket` inside the window, 0 in the 50 s baseline; 9 execs of `/usr/local/bin/node` in the front-end's namespace in those 120 s, 0 in the baseline. The other four repeats are not yet checked; the campaign notes say the fault "restart-loops the front-end, exactly 9 times per injection" (`CAMPAIGN-ISSUES.md` issue 22), which matches. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed.

## Part 1. Background

A process may hold at most `RLIMIT_NOFILE` descriptors (Docker's default is 1024 per
container process). When the table is full, the kernel returns `-EMFILE` from every
descriptor-creating system call. Two things follow:

- **Incoming connections are refused at `accept`.** The listening socket keeps queueing
  them; the callers see timeouts or resets. Node's `net` module throws on an `accept`
  EMFILE and, without a handler, the process exits. The orchestrator restarts it, and the
  new process hits the same limit again if the limit is on the container. That is the
  restart loop.
- **Outgoing connections fail at `socket`.** A service that cannot open a socket to its
  database answers errors immediately, which looks like a dependency failure to its callers.

What the kernel trace shows for this fault: `ret = -24` on `accept4`/`socket`/`openat`
from ONE process; its highest fd sits at a flat ceiling; that service's comm exec'd
several times in the window.

**A true verdict that is not the root cause.** On all 304 v2 runs the tool finds the 10
injected runs. It also gives FD EXHAUSTION for the edge router (`traefik`) in 11 Sock Shop
runs of `anomaly_net`, `code_event_loop_block` and `dns_delay`. There the front-end is
slow, connections pile up in the proxy in front of it, and the proxy reaches its own
default limit (highest fd 1023, thousands of EMFILE, 0 restarts).

| | the injected fault | the cascade |
|---|---|---|
| process | the service whose limit was lowered | the proxy in front of a slow service |
| highest fd | 72-90 (a lowered limit) | 1023 (the default limit) |
| restarts | 6-8 | 0 |
| EMFILE count | 4-168 | 1,258-43,036 |

The tool was NOT changed: a rule on these numbers would be fitted to one application. On
Train Ticket the injected fault itself has 0 restarts and a highest fd of 1308-1528, so
neither number is a general test.

Problems that look similar:

- Host file table full (`ENFILE`, `-23`): every process on the host returns `-23`; host-wide, not one service.
- Ephemeral ports exhausted (`EADDRNOTAVAIL`, `-99`): `connect()` returns `-99` from one client; the limit is on source ports, descriptors are fine.
- Connection-pool / server limit (blueprint 6): `connect()` returns `-111`, or connections are accepted then closed after a small error packet; the client's own fd table is fine; the limit is on the PEER.
- A plain crash loop (bug, OOM kill): execs of the comm repeat, but 0 EMFILE; run blueprint 4 (OOM) or read the exit codes.
- Slow dependency (blueprint 3): long socket waits, 0 EMFILE; nothing fails to open, answers are late.
- A proxy or gateway in front of a slow service: it reaches its own default limit (highest fd 1023, 0 restarts); the descriptor limit is a consequence.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice with the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `fd_pressure.py` | Per process: EMFILE/ENFILE/EADDRNOTAVAIL/ECONNREFUSED counts by call, highest fd seen, execs and exits of that comm in its namespace; the verdict | `fd_pressure.py <slice> <secs> [--top N] [--min-hits 3]` |
| `sched_budget.py` | Per-process run / wait / sleep, to see who stalled behind the failing service | `sched_budget.py <slice> <secs>` |

`FDEV='sched_process_exec|sched_process_exit|syscall_exit_(accept4|accept|socket|socketpair|openat|open|creat|dup|dup2|dup3|pipe2|pipe|epoll_create1|epoll_create|eventfd2|memfd_create|timerfd_create|signalfd4|inotify_init1|connect)'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find where the event rate changes, and choose the start of the fault slice (30 s before the change) and a quiet baseline time. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. window_start is where the rate
changes. This fault is continuous once injected, but its first seconds are the
loudest (the EMFILE burst comes before the first restart), so the window starts where
the change starts. early_start is 30 s BEFORE window_start, not at it: measured, all
23 EMFILE returns fell in the first 6 s after the limit was applied, the front-end
died on them, and the host-wide activity drop that the rate plot shows began ~4 s
later. A slice cut at the drop misses the burst and reads NO FD PRESSURE on the
fault. base_start is a quiet stretch well before early_start.

Write down: `window_start` (where the event rate changes, HH:MM:SS only (no date)), `early_start` (start of the 90 s fault slice, 30 s BEFORE window_start, HH:MM:SS only (no date)), `base_start` (start of a 30 s slice in a quiet stretch well before early_start, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | the three times are chosen |  | go to `pressure` |

### Step 3. Count the EMFILE returns per process in a baseline slice and in the fault slice, and read the verdict. (`pressure`)

```
extract_slice.sh $TRACE <day> <base_start> 30 $WORK/fd_base.txt $FDEV
extract_slice.sh $TRACE <day> <early_start> 90 $WORK/fd_fault.txt $FDEV
fd_pressure.py $WORK/fd_base.txt 30 --top 10
fd_pressure.py $WORK/fd_fault.txt 90 --top 10
```

fd_pressure.py prints one row per process and a verdict line. Read the verdict line
of the fault slice against the baseline. FD EXHAUSTION in any slice you cut,
whichever you called it, is this outcome: the verdict does not depend on which slice
you labelled "fault". A burst of EMFILE from one service followed by the whole stack
going quiet is the front door dying, not a host-wide outage of unknown cause. If the
baseline slice also shows EMFILE from the same process, the limit was already hit
before the window: still FD EXHAUSTION, but say the recording has no clean baseline.
A single EMFILE is reported in the table but not called a fault (the bar is
`--min-hits 3`). There can be several verdict lines for one process (thread names of
the same process): read the pid. If the trace has no `syscall_exit_*` events the
fault is invisible here; say so.

Write down: `fd_process` (the process on the FD EXHAUSTION verdict line (comm, ns, pid), with its highest fd and its restart count), `first_emfile` (the `first at` time on the verdict line).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `exhaustion` | the tool reads FD EXHAUSTION for one process, in any slice | `VERDICT: FD EXHAUSTION ...` | go to `cause` |
| `none` | the tool reads NO FD PRESSURE on both slices, with no NOTE line | `NO FD PRESSURE ...` | **Stop.** Not this fault. Report the negative line word for word. Root cause **rejected**. |
| `refused` | the tool prints NOTE CONNECTS REFUSED (ECONNREFUSED on connect()) with no EMFILE |  | **Stop.** A peer refused the connections. Not this fault; the case goes to blueprint 6 (conn_pool_exhaustion) or blueprint 3 (slow_db). Root cause **rejected**. |
| `ports` | the tool prints NOTE EPHEMERAL PORTS EXHAUSTED with no EMFILE |  | **Stop.** A client-side port limit, not descriptors. Report as `other` with the line. Root cause **rejected**. |

### Step 4. Ask why the descriptors ran out (the process's own limit, or a proxy in front of a slow service), and name who stalled behind it. (`cause`)

```
extract_slice.sh $TRACE <day> <window_start> 10 $WORK/sched.txt
sched_budget.py $WORK/sched.txt 10
```

Before you report this fault, ask why the descriptors ran out. Read the verdict line
of the pressure step again: the process, its highest fd, its restarts. If the process
is a proxy or gateway, its highest fd sits at a default limit (1023), and the service
behind it is slow or failing, the descriptor limit is a consequence. In the injected
Sock Shop runs the process was the service itself, with a highest fd of 72-90 and 6-8
restarts. Neither number is a general test: on Train Ticket the injected fault has 0
restarts and a highest fd of 1308-1528. sched_budget.py shows the blast radius: the
failing service's callers sit in `S` (sleeping on sockets) or see errors. Name the
processes whose sleep rose; they are the effect, not the cause.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `own_limit` | the process on the verdict line is the service itself and its own limit is the cause |  | go to `report` Root cause **confirmed**. |
| `cascade` | the process is a proxy or gateway, its highest fd sits at a default limit (1023), and the service behind it is slow or failing |  | **Stop.** The descriptor limit is a consequence. Report the fault of the service behind it and name the proxy as a victim. Root cause **rejected**. |

### Report

fault_type: fd_exhaustion. Root cause: the service name (the container the index
annotations give for that pid_ns, e.g. `front-end`), then the comm and pid_ns from the
verdict line. A pid_ns id alone is not a service name. The incident window is from the
first EMFILE (the `first at` time) to the end of the window. Evidence: the verdict line
and the baseline's `NO FD PRESSURE` line word for word, the EMFILE count by call, the
highest fd, the restart count. Fix: raise `ulimits.nofile` for that service (compose) or
`prlimit --nofile` on the process; if the highest fd kept climbing before the first
EMFILE, the service leaks descriptors. The trace shows the EMFILE returns, not the limit
value.

## Part 4. Measured, and limits

- One labelled run so far. The tool's bar (`--min-hits 3`) comes from it; a single EMFILE in a 60 s window is reported in the table but not called a fault.
- The trace shows the EMFILE returns, not the limit value. The highest fd seen is a lower bound on the limit (Docker's default 1024; the measured run sat far below it).
- If the trace has no `syscall_exit_*` events the fault is invisible here; say so.
- **Measured on all runs (17-11-2026): a true verdict that is not the root cause.** On all 304 v2 runs the tool finds the 10 injected runs. It also gives FD EXHAUSTION for the edge router (`traefik`) in 11 Sock Shop runs of `anomaly_net`, `code_event_loop_block` and `dns_delay`. There the front-end is slow, connections pile up in the proxy in front of it, and the proxy reaches its own default limit (highest fd 1023, thousands of EMFILE, 0 restarts).
- **Before you report this fault, ask why the descriptors ran out.** If the process is a proxy or gateway, its highest fd sits at a default limit (1023), and the service behind it is slow or failing, the descriptor limit is a consequence. Report the fault of the service behind it and name the proxy as a victim. Per-run lines: `RESULTS.md`.
