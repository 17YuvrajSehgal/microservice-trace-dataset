<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one client holds a server's connections (connection-pool exhaustion)

| | |
|---|---|
| Problem class | Saturation of a shared dependency |
| Root cause this blueprint confirms or rejects | One client keeps many connections to one server open and idle, so the server has no slots left for the others. |
| Evidence | An LTTng kernel trace only, with the `net_dev_queue` event |
| Not used | Logs, metrics, packet contents |

**When to use this.** Services that use a database (or any server with a connection limit) fail at login or wait for a connection, while the database itself looks healthy and fast.

**Status.** This blueprint was parked on 03-11-2026: seen from the application, `connect()` never fails. It works when the trace is read from the other side, the holder. Calibrated on the 10 labelled `conn_pool_exhaustion` runs of both applications and checked on all other v2 runs (17-11-2026). Tool only. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed.

## Part 1. Background

A connection that is open and unused still sends a few bytes now and then (a ping or a
keepalive). In a slice it shows as a connection with packets but no SYN and no FIN: it was
opened before the slice and is not closed in it.

| | the holder | a normal pool |
|---|---|---|
| connections to one server, open all slice, under 1 kB each | **149 (Sock Shop), 1,800 (Train Ticket)** | 159-200 (the database proxy on Train Ticket) |
| the same pair in the baseline slice | **0** | about the same number |

So an idle pool alone is not the fault. The holder is **new**: it is not in the baseline.

The application side gives no firm signal. Measured on one labelled run, 10 s fault window
against 10 s baseline, the catalogue process and its proxy hop: `connect()` returns
854 ok + 610 EINPROGRESS before and 660 ok + 468 EINPROGRESS under the fault, **0 refused**
in both. The application connects through a proxy that always accepts, and MySQL refuses
at the protocol level, so `connect()` never fails.

Problems that look similar:

- A standing pool: a normal connection pool that was there before (159-200 idle connections for the database proxy on Train Ticket). It is in the baseline too and gets the NOTE line. Not the fault.
- A server that accepts connections and then resets them: a different fault, blueprint 22.
- A server port that refuses connections: nothing listens there, the service is down. Not this fault.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `tcp_conns.py` | Connections per server and per client: opened, reset, refused, held; the verdict | `tcp_conns.py <slice> <secs> [baseline_slice]` |

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a time inside the suspect window and one before it, for two 20 s slices. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Pick a time inside the suspect
window (slice_time) and one before it (base_time). Both slices are 20 s and must lie
inside the trace.

Write down: `slice_time` (start of the 20 s slice inside the suspect window, HH:MM:SS only (no date)), `base_time` (start of a 20 s slice before the suspect window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | a time inside the suspect window and a time before it are chosen |  | go to `connections` |
| `no_window` | no clear suspect window; two times were chosen anyway |  | go to `connections` |

### Step 3. Find a client that holds many idle connections to one server and is not in the baseline, and read the verdict. (`connections`)

```
extract_slice.sh $TRACE <day> <slice_time> 20 $WORK/net.txt net_dev_queue
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/base.txt net_dev_queue
tcp_conns.py $WORK/net.txt 20 $WORK/base.txt
```

The baseline is required. Without it the tool cannot tell the holder from a normal
pool. tcp_conns.py prints connections per server (opened, accepted then reset,
refused), the clients that hold connections open (held, idle, and `before` = the
connections of that pair in the baseline slice), and VERDICT lines. It can print more
than one VERDICT line.
A held connection has packets in the slice but was not opened and not ended in it.
Idle means held with 1024 bytes of payload or less.
A line that starts with `NOTE: a standing pool, not new` is a normal connection pool
that was there before. It is not the fault.
A connection that sends nothing in the slice is invisible.
The trace shows the holder, not the damage: that the server refused the other
clients is in the payload and not in the trace.
To find the incident window, cut earlier slices to find the first one with the verdict.

Write down: `holder` (the client on the verdict line (comm, pid_ns, address)), `held_server` (the server address and port on the verdict line (A:port), the resource the holder fills).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `new_holder` | the tool reads NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE for one client and one server address and port | `VERDICT: NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE ...` | go to `report` Root cause **confirmed**. |
| `standing_pool` | the only line about held connections is `NOTE: a standing pool, not new`, and no client has the new-client verdict | `NOTE: a standing pool, not new ...` | **Stop.** A normal connection pool that was there before. Not the fault. Root cause **rejected**. |
| `held_no_baseline` | the tool reads CONNECTIONS HELD OPEN AND IDLE (no baseline given, so not known to be new) | `VERDICT: CONNECTIONS HELD OPEN AND IDLE ...` | **Stop.** The baseline is required. Without it the tool cannot tell the holder from a normal pool. Root cause **inconclusive**. |
| `reset_storm` | the tool reads SERVER ACCEPTS AND THEN RESETS CONNECTIONS and no client has the new-client verdict | `VERDICT: SERVER ACCEPTS AND THEN RESETS CONNECTIONS ...` | **Stop.** A different fault: blueprint 22. Hand the case to blueprint `22_error_storm`. Root cause **rejected**. |
| `refused` | the tool reads SERVER PORT REFUSES CONNECTIONS and no client has the new-client verdict | `VERDICT: SERVER PORT REFUSES CONNECTIONS ...` | **Stop.** Not this fault. Nothing listens on that port; the service is down. Root cause **rejected**. |
| `none` | the tool reads NO RESET STORM, NO NEW HELD CONNECTIONS | `VERDICT: NO RESET STORM, NO NEW HELD CONNECTIONS ...` | **Stop.** Not this fault. Root cause **rejected**. |

### Report

fault_type: conn_pool_exhaustion. Root cause service: the client on the verdict line
(`comm`, `pid_ns`, address). The server on that line is the resource it fills. Incident
window: cut earlier slices to find the first one with the verdict. Evidence: the verdict
line word for word. Fix: stop or fix the client that does not return its connections;
then look at the connection limit of the server.

## Part 4. Measured, and limits

- Per-run lines: `22_error_storm/RESULTS.md` (the same job checked both blueprints).
- **10 of 10 fault runs, 0 false alarms in 292 other runs.** 90 Train Ticket runs and 1 Sock Shop run have a standing pool of 83 to 200 idle connections; all are in the baseline too and get the NOTE line.
- **The baseline rule was added after the first sweep.** Without it the standing pools read as the fault (91 runs).
- **A connection that sends nothing in the slice is invisible.** The holder here pings every connection every 10 s, so a 20 s slice sees all of them. A holder that never sends would only show through TCP keepalives, if they are on.
- **The trace shows the holder, not the damage.** That the server refused the other clients is in the MySQL error packet ("Too many connections"), which is payload and not in the trace. Seen from the application, connections get shorter and smaller (table below).
- The bars (50 held connections, 90% of the connections of the pair, under 1 kB each) were set before the sweep and not changed.
