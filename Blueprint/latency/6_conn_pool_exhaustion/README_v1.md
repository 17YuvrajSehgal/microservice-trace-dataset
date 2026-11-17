# Blueprint: one client holds a server's connections (connection-pool exhaustion)

| | |
|---|---|
| Problem class | Saturation of a shared dependency |
| Root cause this blueprint confirms or rejects | One client keeps many connections to one server open and idle, so the server has no slots left for the others |
| Evidence | An LTTng kernel trace only, with the `net_dev_queue` event |
| Not used | Logs, metrics, packet contents |

**When to use this.** Services that use a database (or any server with a connection limit)
fail at login or wait for a connection, while the database itself looks healthy and fast.

> **Honest status.** This blueprint was parked on 03-11-2026: seen from the application,
> `connect()` never fails (the old note is kept at the end). It works when the trace is read
> from the other side, the holder. Calibrated on the 10 labelled `conn_pool_exhaustion` runs
> of both applications and checked on all other v2 runs (17-11-2026). Tool only; the agent
> has not been run on it.

---

## Part 1. Background

A connection that is open and unused still sends a few bytes now and then (a ping or a
keepalive). In a slice it shows as a connection with packets but no SYN and no FIN: it was
opened before the slice and is not closed in it.

| | the holder | a normal pool |
|---|---|---|
| connections to one server, open all slice, under 1 kB each | **149 (Sock Shop), 1,800 (Train Ticket)** | 159-200 (the database proxy on Train Ticket) |
| the same pair in the baseline slice | **0** | about the same number |

So an idle pool alone is not the fault. The holder is **new**: it is not in the baseline.

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `tcp_conns.py` | Connections per server and per client: opened, reset, refused, held; the verdict | `tcp_conns.py <slice> <secs> [baseline_slice]` |
| `victim_info.py` | Who a pid is | see blueprint 2 |
| `connect_census.py` | `connect()` calls per process (from the parked version; not needed for the verdict) | |

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Pick a time inside the suspect window (`T`) and one before it (`T0`).

### Step 2. Two slices of 20 s
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $T  20 $WORK/net.txt  'net_dev_queue'
bash $TOOLS/extract_slice.sh $TRACE $DAY $T0 20 $WORK/base.txt 'net_dev_queue'
```
The baseline is required. Without it the tool cannot tell the holder from a normal pool.

### Step 3. The decisive check
```bash
python3 $TOOLS/tcp_conns.py $WORK/net.txt 20 $WORK/base.txt
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE: <comm> (pid_ns N) at <ip> holds K connections to A:port; it opened 0 and ended 0 in the slice, B bytes per connection; 0 in the baseline` | **This fault.** That client fills the server at A:port |
| `NOTE: a standing pool, not new: ...` | A normal connection pool that was there before. Not the fault |
| `VERDICT: SERVER ACCEPTS AND THEN RESETS CONNECTIONS: ...` | A different fault: blueprint 22 |
| `VERDICT: NO RESET STORM, NO NEW HELD CONNECTIONS (...)` | Not this fault |

### Step 4. Submit
- `fault_type`: `conn_pool_exhaustion`.
- `root_cause_service`: the client on the verdict line (`comm`, `pid_ns`, address). The
  server on that line is the resource it fills.
- `incident_window`: cut earlier slices to find the first one with the verdict.
- `evidence`: the verdict line word for word.
- Fix: stop or fix the client that does not return its connections; then look at the
  connection limit of the server.

---

## Part 4. Measured, and limits

- Per-run lines: `22_error_storm/RESULTS.md` (the same job checked both blueprints).
- **10 of 10 fault runs, 0 false alarms in 292 other runs.** 91 Train Ticket runs and 1 Sock
  Shop run have a standing pool of 83 to 200 idle connections; all are in the baseline too
  and get the NOTE line.
- **The baseline rule was added after the first sweep.** Without it the standing pools read
  as the fault (92 runs).
- **A connection that sends nothing in the slice is invisible.** The holder here pings every
  connection every 10 s, so a 20 s slice sees all of them. A holder that never sends would
  only show through TCP keepalives, if they are on.
- **The trace shows the holder, not the damage.** That the server refused the other clients
  is in the MySQL error packet ("Too many connections"), which is payload and not in the
  trace. Seen from the application, connections get shorter and smaller (table below).
- The bars (50 held connections, 90% of the connections of the pair, under 1 kB each) were
  set before the sweep and not changed.

## The parked note (03-11-2026): what the application side shows

Measured on `conn_pool_exhaustion_aggressive_steady_r1`, 10 s fault window against 10 s
baseline, the `app` (catalogue) process and its toxiproxy hop:

| | baseline | fault |
|---|---|---|
| `connect()` returns | 854 ok + 610 EINPROGRESS, **0 refused** | 660 ok + 468 EINPROGRESS, **0 refused** |
| connections closed in the window | 1462 | 1127 |
| lifetime p50 / p90 | 0.6 / 4.3 ms | 0.8 / 2.5 ms |
| bytes read per connection, p50 | 52 | 27 |

The application connects through a proxy that always accepts, and MySQL refuses at the
protocol level, so `connect()` never fails. That is why this side gives no firm signal.
