# Blueprint: name lookups time out and are sent again (unreliable resolver)

| | |
|---|---|
| Problem class | Configuration / dependency (the resolver loses queries) |
| Root cause this blueprint confirms or rejects | One service's DNS queries or answers are lost; each lookup waits for a timeout and is sent again |
| Evidence | An LTTng kernel trace only, with the `sendto`, `poll` and `close` system calls |
| Not used | Logs, metrics, packet contents |

**When to use this.** A few requests take seconds while the median and the 95th percentile
look healthy; CPU, disk and network are idle; nothing reports an error.

> **Honest status.** Calibrated on the 5 labelled Sock Shop `dns_delay` runs (60% of the
> front-end's queries to the resolver dropped) and checked on the other 297 runs of both
> applications. **Only 3 of the 5 labelled runs are a clean case** (Part 4). Train Ticket has
> no runs of this fault.

---

## Part 1. Background

A lookup by the C library resolver is a short sequence of system calls in one thread:

```
socket, bind            a fresh UDP socket
sendto (with address)   the query (two of them: A and AAAA)
poll(timeout 2500 ms)   wait for the answer
close
```

A healthy lookup takes 0.1-0.4 ms. When a query is lost, `poll` returns 0 after 2.5 s and
the **same thread sends again on the same socket**. The slowest lookups take 5.0 s. The tool
counts lookups with that timeout-then-resend.

| | this fault | a program that keeps restarting | healthy |
|---|---|---|---|
| lookups that time out and are sent again | **76-88%** | 9-13% | 0-1% |
| the program's pids in 60 s | 1 | 4-6 | 1 |

A program that restarts loses lookups while it starts, with a healthy resolver (measured on
the 5 `fd_exhaustion` runs, where the front-end crash-loops). So the tool looks at restarts
before it blames the resolver.

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `dns_retry.py` | Lookups per program, timeouts, resends, the verdict | `dns_retry.py <slice> <secs>` |
| `victim_info.py` | Who a pid is | see blueprint 2 |

```bash
DNSEV='syscall_entry_sendto|syscall_entry_poll|syscall_exit_poll|syscall_entry_close|sched_process_exec'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Pick a time inside the suspect window (`T`).

### Step 2. One slice of 60 s
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $T 60 $WORK/dns.txt "$DNSEV"
```
It must be long: lookups are rare (about one every 2 s here, because connections are pooled).

### Step 3. The decisive check
```bash
python3 $TOOLS/dns_retry.py $WORK/dns.txt 60
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: NAME LOOKUPS TIME OUT: <comm> (pid_ns N) had K of M lookups time out and be sent again (P%), slowest S s, L s lost in total` | **This fault.** That program's resolver path loses queries |
| `VERDICT: LOOKUPS TIME OUT IN A RESTARTING PROGRAM: <comm> (pid_ns N) ran as X different processes ...` | Not proven. The program restarts; find out why first (blueprint 12 for a descriptor limit) |
| `VERDICT: NO LOOKUP TIMEOUTS (most: K of M by <comm>; ...)` | Not this fault |

The table has one row per program: `lookups`, `resent`, `gave up`, `slowest s`, `lost s`,
and `pids` (more than one means it restarted in the slice).

### Step 4. Submit
- `fault_type`: `dns_delay`.
- `root_cause_service`: the program and container from the verdict line (`comm`, `pid_ns`). It
  is the victim of the resolver, and the place where the fix goes.
- `incident_window`: cut earlier slices to find the first one with the verdict.
- `evidence`: the verdict line word for word.
- Fix: repair or replace the resolver; cache lookups; use addresses for internal calls.

---

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **3 of 5 labelled runs are clean** (r2, r4, r5: 76-88% of lookups resent, one pid). In r1 and
  r3 the front-end crash-loops (4 and 6 pids in 60 s) and only 10-11% of lookups time out,
  the same as in the `fd_exhaustion` runs. The tool says "restarting program" for them. Whether
  the DNS fault caused the first crash in those two runs is not shown.
- **r4 is a real injection.** The campaign notes call it failed (no metric moved). The kernel
  shows 28 of 32 lookups timing out.
- **The restart verdict was added after the sweep.** The first rule (3 resent lookups, 5% of
  the program's lookups) fired on all 5 `fd_exhaustion` runs.
- **Only resolvers that use `sendto` with an address and wait in `poll` are seen**: musl (the
  Node front-end here), and glibc when it does not connect first. Go and Java resolve
  differently and are not counted. So this was measured on one program of one application.
- The destination of a `sendto` is not in the trace, so any UDP protocol with the same
  send, poll, resend pattern would be counted as a lookup.
