# Blueprint: a service that ran out of file descriptors (fd_exhaustion)

| | |
|---|---|
| Problem class | Resource limit (per-process) |
| Root cause this blueprint confirms or rejects | One service's process hit its **open-file limit** (`RLIMIT_NOFILE`). Every call that needs a new descriptor — `accept4` for an incoming connection, `socket` for an outgoing one, `openat`, `pipe2`, `epoll_create1` — fails with **EMFILE** (`ret = -24`). The service then drops or refuses requests, and a Node/Go service usually **crashes and restarts** on the first EMFILE in `accept`, so the symptom is a restart loop |
| Evidence | An LTTng kernel trace only: `metadata`, the channel files, `index/` |
| Not used | Logs ("EMFILE: too many open files"), container_file_descriptors metrics, application counters |

**When to use this.** The selector saw EMFILE/ENFILE returns, or a service restarting repeatedly, or
an operator reports "connections refused / too many open files" on one service.

> **Honest status.** Calibrated on one labelled Sock Shop v2 run (`fd_exhaustion_aggressive_steady_r1`:
> the front-end's `RLIMIT_NOFILE` lowered to just above its idle use for 120 s). Measured: **23 EMFILE
> returns by `node` on `accept4`/`socket` inside the window, 0 in the 50 s baseline; 9 execs of
> `/usr/local/bin/node` in the front-end's namespace in those 120 s, 0 in the baseline.** The other
> four repeats are not yet checked; the campaign notes say the fault "restart-loops the front-end,
> exactly 9 times per injection" (`CAMPAIGN-ISSUES.md` issue 22), which matches.

---

## Part 1. Background

A process may hold at most `RLIMIT_NOFILE` descriptors (Docker's default is 1024 per container
process). When the table is full, the kernel returns `-EMFILE` from every descriptor-creating
system call. Two things follow:

- **Incoming connections are refused at `accept`.** The listening socket keeps queueing them; the
  callers see timeouts or resets. Node's `net` module throws on an `accept` EMFILE and, without a
  handler, the process exits — the orchestrator restarts it — and the new process hits the same
  limit again if the limit is on the container. That is the restart loop.
- **Outgoing connections fail at `socket`.** A service that cannot open a socket to its database
  answers errors immediately, which looks like a dependency failure to its callers.

**What distinguishes it from its lookalikes:**

| Cause | What the kernel trace shows | How it differs |
|---|---|---|
| **fd exhaustion (this fault)** | `ret = -24` on `accept4`/`socket`/`openat` from ONE process; its highest fd sits at a flat ceiling; that service's comm exec'd several times in the window | — |
| Host file table full (`ENFILE`, `-23`) | every process on the host returns `-23` | host-wide, not one service |
| Ephemeral ports exhausted (`EADDRNOTAVAIL`, `-99`) | `connect()` returns `-99` from one client | the limit is on source ports, not descriptors; descriptors are fine |
| Connection-pool / server limit (`6_conn_pool_exhaustion`) | `connect()` returns `-111`, or connections are accepted then closed after a small error packet; the client's own fd table is fine | the limit is on the PEER |
| A plain crash loop (bug, OOM kill) | execs of the comm repeat, but 0 EMFILE | run `4_svc_mem_cap` (OOM) or read the exit codes |
| Slow dependency (`3_slow_db`) | long socket waits, 0 EMFILE | nothing fails to open; answers are late |

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice with the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `fd_pressure.py` | Per process: EMFILE/ENFILE/EADDRNOTAVAIL/ECONNREFUSED counts by call, highest fd seen, execs and exits of that comm in its namespace; the verdict | `fd_pressure.py <slice> <secs> [--top N] [--min-hits 3]` |
| `sched_budget.py` | Per-process run / wait / sleep, to see who stalled behind the failing service | `sched_budget.py <slice> <secs>` |

The event pattern for the slice:

```bash
FDEV='sched_process_exec|sched_process_exit|syscall_exit_(accept4|accept|socket|socketpair|openat|open|creat|dup|dup2|dup3|pipe2|pipe|epoll_create1|epoll_create|eventfd2|memfd_create|timerfd_create|signalfd4|inotify_init1|connect)'
```

---

## Part 3. Procedure

### Step 1. Orient

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Write down `DAY`, the recording span, and where the rate changes (`WINDOW_START`). This fault
is **continuous** once injected, but its first seconds are the loudest (the EMFILE burst comes
before the first restart), so the window starts where the change starts.

### Step 2. Cut a fault slice and a baseline slice

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 60 $WORK/fd_fault.txt "$FDEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   30 $WORK/fd_base.txt  "$FDEV"
```
`BASE_START` = a quiet stretch before the window. 60 s of the fault window is enough: measured,
the 23 EMFILE returns all fell in the first 6 s and the restarts spread over the window.

### Step 3. The decisive check

```bash
python3 $TOOLS/fd_pressure.py $WORK/fd_fault.txt 60 --top 10
python3 $TOOLS/fd_pressure.py $WORK/fd_base.txt  30 --top 10
```

Read the verdict line of the fault slice against the baseline:

| Verdict line | Meaning |
|---|---|
| `VERDICT: FD EXHAUSTION: <comm> (ns N, pid P): K EMFILE returns on <calls> in S s (first at T); highest fd seen F; R restarts of <comm> in that namespace` — and the baseline says `NO FD PRESSURE` | **This fault.** `<comm>` in namespace `N` is the victim and its own limit is the cause. `R >= 1` with `K >= 3` is the restart-loop shape |
| `NO FD PRESSURE: 0 EMFILE/ENFILE returns ...` on both slices | Not this fault. Stop here; report the negative line word for word |
| `NOTE: CONNECTS REFUSED: <comm> ...: K ECONNREFUSED on connect()` with no EMFILE | A peer refused: hand to `6_conn_pool_exhaustion` / `3_slow_db` |
| `NOTE: EPHEMERAL PORTS EXHAUSTED: ...` | A client-side port limit, not descriptors; report as `other` with the line |
| `NOTE: RESTART LOOP: <comm> (ns N) exec'd R times` with 0 EMFILE | A crash loop with another cause; not this fault |
| the baseline slice ALSO shows EMFILE from the same process | The limit was already hit before the window: still this fault, but say the recording has no clean baseline |

### Step 4. Blast radius (one call)

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/sched.txt
python3 $TOOLS/sched_budget.py $WORK/sched.txt 10
```
The failing service's callers sit in `S` (sleeping on sockets) or see errors. Name the processes
whose sleep rose; they are the effect, not the cause.

### Step 5. Submit

- `fault_type`: `fd_exhaustion`.
- `root_cause_service`: the comm and pid_ns from the verdict line (the service whose limit was hit).
- `culprit_kind`: `container` (the limit is set on the container/process), `culprit_thread`: `none`.
- `victim_thread`: `none` on a container host; on a bare-metal host the comm/tid that returned EMFILE.
- `incident_window`: from the first EMFILE (the `first at` time) to the end of the window.
- `evidence`: the verdict line and the baseline's `NO FD PRESSURE` line word for word, the EMFILE
  count by call, the highest fd, the restart count.
- Fix: raise `ulimits.nofile` for that service (compose) or `prlimit --nofile` on the process; if
  the highest fd kept climbing before the first EMFILE, the service leaks descriptors.

---

## Part 4. Limits

- One labelled run so far. The tool's bar (`--min-hits 3`) comes from it; a single EMFILE in a
  60 s window is reported in the table but not called a fault.
- The trace shows the EMFILE returns, not the limit value. The highest fd seen is a lower bound on
  the limit (Docker's default 1024; the measured run sat far below it).
- If the trace has no `syscall_exit_*` events the fault is invisible here; say so.
