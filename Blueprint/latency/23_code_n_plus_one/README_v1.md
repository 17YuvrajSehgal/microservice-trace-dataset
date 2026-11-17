# Blueprint: a service makes more calls to a healthy dependency per request (N+1 queries)

| | |
|---|---|
| Problem class | Too much work (a code defect) |
| Root cause this blueprint confirms or rejects | One service makes more calls to one dependency for each request it receives than it did before, while that dependency answers as fast as before |
| Evidence | An LTTng kernel trace only, with the `net_dev_queue` event |
| Not used | Logs, metrics, packet contents, source code |

**When to use this.** A service got slower or busier after a release. Its database looks
healthy: fast answers, no errors, no loss. CPU, disk and memory checks find nothing.

> **Honest status. This is the weakest blueprint in the set.** Calibrated on the 6 labelled
> `code_n_plus_one` runs (Sock Shop catalogue: one extra query per row of a list). The signal
> is the same in all 6 runs, but it is small (1.45 to 1.57 times), the bar (1.35) is fitted
> between it and the nearest healthy pair (1.28), and it only works with a baseline at the
> same steady load. Tool only; the agent has not been run on it.

---

## Part 1. Background

The packets show, for every connection, when the client sends data and when the server
answers. A call is one such exchange. For each service the tool counts the calls it makes to
each dependency and divides by the requests the service itself received in the same slice.

| catalogue -> its database | healthy | this fault |
|---|---|---|
| calls per request received | 2.0-2.8 | **3.15-3.83** |
| the same, against a slice after the fault | 0.97-1.23 times | **1.45-1.57 times** |
| time per answer | 0.4-0.5 ms | 0.35-0.38 ms (not slower) |

Two things can look the same and are not this fault:

- **More calls to a slow or lossy dependency.** Those are retries. The tool requires that
  the answers did not get slower.
- **A different mix of user actions.** Calls per request depend on what the users do. A
  baseline cut while the load was still ramping up gave 1.6 times for a healthy service
  (a Java service -> its MongoDB) in many runs. The baseline must be at the same steady load.

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `call_fanout.py` | Calls per request received, answer time and overlap, per client and server; the verdict | `call_fanout.py <slice> <secs> <baseline_slice>` |
| `victim_info.py` | Who a pid is | see blueprint 2 |

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Pick a time inside the suspect window (`T`) and a healthy time (`T0`) where the data rate is
flat and at the same level. If the only healthy period is a ramp-up, say so and treat the
verdict as weak.

### Step 2. Two slices of 20 s
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $T  20 $WORK/net.txt  'net_dev_queue'
bash $TOOLS/extract_slice.sh $TRACE $DAY $T0 20 $WORK/base.txt 'net_dev_queue'
```

### Step 3. The decisive check
```bash
python3 $TOOLS/call_fanout.py $WORK/net.txt 20 $WORK/base.txt
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: CALL AMPLIFICATION: <comm> (pid_ns N) at <ip> makes R calls to A:port per request it receives, R0 in the baseline (K x); each answer takes T ms (T0 before)` | **This fault**, if the baseline was at steady load. The service on the line is the culprit; the server is healthy |
| `VERDICT: NO CALL AMPLIFICATION (largest rise with answers not slower: K x for ...)` | Not this fault |

More than one verdict line in one run points at a bad baseline (the mix of user actions
changed), not at several defects.

### Step 4. Submit
- `fault_type`: `code_n_plus_one`.
- `root_cause_service`: the client on the verdict line (`comm`, `pid_ns`, address).
- `evidence`: the verdict line word for word.
- Fix: in the code of that service, fetch the rows in one query (or one batched query) and
  not one query per row. The trace cannot name the function.

---

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Against a slice after the fault (steady load): 6 of 6, 0 false alarms in the 175 other
  runs that could be judged.** 123 runs could not be judged: no client and server pair has
  200 calls and 200 received requests in both slices (104 Train Ticket runs and 19
  Sock Shop runs; 3 of them are failed slice cuts).
- **Against a slice before the fault (in the load ramp-up): not usable.** The 6 fault runs
  are found, but a healthy pair rises 1.58 to 1.65 times in many runs of other families.
- **The margin is thin.** Fault runs: 1.45 to 1.57. Highest healthy pair that passes the
  other conditions: 1.28. The bar of 1.35 is fitted to this data.
- **The rule was changed twice after sweeps.** First guess: 3 times, any pair. Final:
  1.35 times, answers at most 1.1 times slower, 200 calls and 200 received requests. The
  final rule was applied to the saved tables of job 2880078, not run again on the slices.
- **One defect in one service.** The size of the rise depends on how often the list endpoint
  is called and how many rows it returns. Another service would give another number.
- A call is counted as "client data, then server data" on one connection. Commands that get
  no answer (a statement close) are merged into the next call.
