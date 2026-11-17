# Blueprint: a server side that accepts connections and then resets them

| | |
|---|---|
| Problem class | Errors (a dependency path is broken) |
| Root cause this blueprint confirms or rejects | One server address:port accepts new TCP connections and immediately resets them, so every client of it fails |
| Evidence | An LTTng kernel trace only, with the `net_dev_queue` event |
| Not used | Logs, metrics, packet contents |

**When to use this.** Requests fail fast with errors; CPU, disk and memory are quiet; nothing
is slow. In the logs the clients report "connection reset" or "communications link failure".

> **Honest status.** Calibrated on the 16 labelled `error_storm` runs of Sock Shop and Train
> Ticket (a proxy in front of the database resets every connection) and checked on all other
> v2 runs. Tool only; the agent has not been run on it. Two rules were changed after the
> first sweep (Part 4).

---

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

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `tcp_conns.py` | Connections per server and per client: opened, reset, refused, held; the verdict | `tcp_conns.py <slice> <secs> [baseline_slice]` |
| `victim_info.py` | Who a pid is | see blueprint 2 |

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

### Step 3. The decisive check
```bash
python3 $TOOLS/tcp_conns.py $WORK/net.txt 20 $WORK/base.txt
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: SERVER ACCEPTS AND THEN RESETS CONNECTIONS: A:port reset K of the M connections opened to it (P%); N clients, most from <comm> (pid_ns ..) at <ip>; 0.0 kB came back` | **This fault.** The component at A:port (or the path behind it) is broken |
| `VERDICT: SERVER PORT REFUSES CONNECTIONS: A:port refused K of the M ...` | Not this fault. The service at A:port is down or restarting; find out why (blueprint 4 for a memory kill, 12 for a descriptor limit, 15 for a freeze) |
| `VERDICT: NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE: ...` | A different fault: blueprint 6 |
| `VERDICT: NO RESET STORM, NO NEW HELD CONNECTIONS (...)` | Not this fault |

A refusal that is also in the baseline slice is a standing condition, not the incident. On
Train Ticket one service is refused on `127.0.0.1:5672` in every run, also the healthy ones
(it looks for a message broker that is not deployed).

### Step 4. Submit
- `fault_type`: `error_storm`.
- `root_cause_service`: the server address and port from the verdict line. The clients on
  that line are the victims.
- `incident_window`: cut earlier slices to find the first one with the verdict.
- `evidence`: the verdict line word for word.
- Fix: repair the component at that address (here a proxy rule that resets connections).

---

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **16 of 16 fault runs, 0 false alarms in 286 other runs.** Fault runs: 10 to 50 connections,
  100% reset, nothing comes back. Closest other family: `anomaly_net` (packet loss), where
  13 to 32 of 92 to 127 new connections end in a server reset (10 to 25%); the bar is 50%.
- **Two rules were changed after the first sweep.** (1) Resets are counted per server over
  all its clients; per client, 7 of 8 Train Ticket runs were missed, because about 20
  services share the resets. (2) "Refused" is split from "accepted, then reset"; before
  that, every Train Ticket run and the runs with a dead service fired.
- **The count bar (5) was lowered from a guess of 20 after the first pilot run**, before the
  sweep. A client that is always reset stops trying.
- **Only the aggressive setting was collected** (reset at once). The recipe's subtle setting
  (the connection stalls 2 s and then dies) is not covered, and it may not end in a RST.
- The trace shows who resets, not why. A server that resets because its own backend failed
  looks the same.
- The server is taken to be the side with the fixed port (below 32768, or the smaller one).
