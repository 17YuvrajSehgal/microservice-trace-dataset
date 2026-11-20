<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a server side that accepts connections and then resets them

| | |
|---|---|
| Problem class | Errors (a dependency path is broken) |
| Root cause this blueprint confirms or rejects | One server address:port accepts new TCP connections and immediately resets them, so every client of it fails. |
| Evidence | An LTTng kernel trace only, with the `net_dev_queue` event |
| Not used | Logs, metrics, packet contents |

**When to use this.** Requests fail fast with errors; CPU, disk and memory are quiet; nothing is slow. In the logs the clients report "connection reset" or "communications link failure".

**Status.** Calibrated on the 16 labelled `error_storm` runs of Sock Shop and Train Ticket (a proxy in front of the database resets every connection) and checked on all other v2 runs. Tool only; the agent has not been run on it. Two rules were changed after the first sweep (see Measured). Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed on the second try; the first try cut its slice 14 s after the fault ended and rejected.

## Part 1. Background

A TCP connection starts with SYN from the client and SYN+ACK from the server. Three endings
look alike to the application and are different faults:

| what the packets show | meaning |
|---|---|
| SYN, SYN+ACK, then **RST from the server** | the server side accepted and then dropped the connection: **this fault** |
| SYN, then RST with no SYN+ACK | refused: nothing listens on that port (the service is down or restarting) |
| SYN, SYN+ACK, data, FIN | healthy |

A client that is reset every time backs off. Measured on Sock Shop: the catalogue service
opens about 920 database connections per 20 s when healthy and 10 to 12 under this fault,
all of them reset. So the count is small and the share is what matters.

Problems that look similar:

- A refused connection (SYN, then RST with no SYN+ACK): nothing listens on that port; the service is down or restarting (blueprint 4 for a memory kill, 12 for a descriptor limit, 15 for a freeze).
- A refusal that is also in the baseline slice: a standing condition, not the incident. On Train Ticket one service is refused on `127.0.0.1:5672` in every run, also the healthy ones.
- A new client that holds connections open and idle: a different fault, blueprint 6.
- anomaly_net (packet loss): 13 to 32 of 92 to 127 new connections end in a server reset (10 to 25%); the bar is 50%.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `tcp_conns.py` | Connections per server and per client: opened, reset, refused, held; the verdict | `tcp_conns.py <slice> <secs> [baseline_slice]` |
| `victim_info.py` | Who a pid is | `victim_info.py <sched_slice> <secs> <pid>` |

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
window (slice_time) and one before it (base_time). If the times came with the case,
check them against the table and keep them if they fit. Both slices are 20 s and
must lie inside the trace.

Write down: `slice_time` (start of the 20 s slice inside the suspect window, HH:MM:SS only (no date)), `base_time` (start of a 20 s slice before the suspect window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | a time inside the suspect window and a time before it are chosen |  | go to `connections` |
| `no_window` | no clear suspect window; two times were chosen anyway |  | go to `connections` |

### Step 3. Count, per server, the new connections that were accepted and then reset, and read the verdict. (`connections`)

```
extract_slice.sh $TRACE <day> <slice_time> 20 $WORK/net.txt net_dev_queue
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/base.txt net_dev_queue
tcp_conns.py $WORK/net.txt 20 $WORK/base.txt
```

tcp_conns.py prints connections per server (opened, accepted then reset, refused)
and per client (held), and VERDICT lines. Always give the baseline slice.
"Accepted, then reset" means the server answered the SYN and then sent a RST.
"Refused" means a RST with no answer to the SYN: nothing listens on that port. They
are different faults. A client that is reset every time backs off, so the count is
small and the share is what matters.
The tool can print more than one VERDICT line (one per server). A refusal that is
also in the baseline slice is a standing condition, not the incident: on Train
Ticket one service is refused on `127.0.0.1:5672` in every run, also the healthy
ones (it looks for a message broker that is not deployed). So a REFUSES line for
such a port next to an ACCEPTS AND THEN RESETS line does not change the outcome. To
see the baseline's own refusals, run `tcp_conns.py $WORK/base.txt 20`.
A line that starts with `NOTE: a standing pool, not new` is not a verdict.
The server is taken to be the side with the fixed port (below 32768, or the smaller
one). The trace shows who resets, not why.
To find the incident window, cut earlier slices to find the first one with the verdict.

Write down: `reset_server` (the server address and port on the verdict line (A:port)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `reset_storm` | the tool reads SERVER ACCEPTS AND THEN RESETS CONNECTIONS for one server address and port | `VERDICT: SERVER ACCEPTS AND THEN RESETS CONNECTIONS ...` | go to `report` Root cause **confirmed**. |
| `refused` | the tool reads SERVER PORT REFUSES CONNECTIONS and no server has the accepts-and-then-resets verdict | `VERDICT: SERVER PORT REFUSES CONNECTIONS ...` | **Stop.** Not this fault. The service at A:port is down or restarting; find out why (blueprint 4 for a memory kill, 12 for a descriptor limit, 15 for a freeze). A refusal that is also in the baseline slice is a standing condition, not the incident. Root cause **rejected**. |
| `new_holder` | the tool reads NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE and no server has the accepts-and-then-resets verdict | `VERDICT: NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE ...` | **Stop.** A different fault: blueprint 6 (6_conn_pool_exhaustion). Root cause **rejected**. |
| `held_no_baseline` | the tool reads CONNECTIONS HELD OPEN AND IDLE (no baseline given, so not known to be new) | `VERDICT: CONNECTIONS HELD OPEN AND IDLE ...` | **Stop.** Not this fault. No baseline was given, so the holder is not known to be new. Held connections are a different fault: blueprint 6 (6_conn_pool_exhaustion). Root cause **rejected**. |
| `no_storm` | the tool reads NO RESET STORM, NO NEW HELD CONNECTIONS | `VERDICT: NO RESET STORM, NO NEW HELD CONNECTIONS ...` | **Stop.** No server resets the connections it accepts. Not this fault. Root cause **rejected**. |

### Report

fault_type: error_storm. Root cause service: the server address and port from the
verdict line. The clients on that line are the victims. Evidence: the verdict line word
for word. Fix: repair the component at that address (here a proxy rule that resets
connections). The trace shows who resets, not why.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **16 of 16 fault runs, 0 false alarms in 286 other runs.** Fault runs: 10 to 50 connections, 100% reset, nothing comes back. Closest other family: `anomaly_net` (packet loss), where 13 to 32 of 92 to 127 new connections end in a server reset (10 to 25%); the bar is 50%.
- **Two rules were changed after the first sweep.** (1) Resets are counted per server over all its clients; per client, 7 of 8 Train Ticket runs were missed, because about 20 services share the resets. (2) "Refused" is split from "accepted, then reset"; before that, every Train Ticket run and the runs with a dead service fired.
- **The count bar (5) was lowered from a guess of 20 after the first pilot run**, before the sweep. A client that is always reset stops trying.
- **Only the aggressive setting was collected** (reset at once). The recipe's subtle setting (the connection stalls 2 s and then dies) is not covered, and it may not end in a RST.
- The trace shows who resets, not why. A server that resets because its own backend failed looks the same.
- The server is taken to be the side with the fixed port (below 32768, or the smaller one).
