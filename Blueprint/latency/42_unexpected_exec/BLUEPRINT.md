<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: programs never seen in a container start there (a shell in a service)

| | |
|---|---|
| Problem class | Security (code execution) |
| Root cause this blueprint confirms or rejects | Someone runs a shell and tools inside a service container, so programs that container never runs start there. |
| Evidence | An LTTng kernel trace only, with `sched_process_exec` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service may be compromised; nothing is slow or failing.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-4 runs. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

Every container runs the same few programs. `new_programs.py` lists, per container (pid namespace), the programs
started in the suspect slice that never started there in the baseline slice. The host's namespace is left out:
monitoring scripts start about 1,280 programs a minute there.

| | this fault (front-end) | other containers |
|---|---|---|
| new programs in 60 s | **8**: cat, env, id, ls, ps, sh, uname, wc (24 starts) | 0 |

Problems that look similar:

- A deployment or restart: the service's own program starts again (not new in a 60 s baseline only if it ran before).
- Health checks that run a command in the container: the same program every time, in the baseline too.
- The host's own scripts: a different namespace, left out.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `new_programs.py` | Programs started per container that never started there before; the verdict | `new_programs.py <baseline_slice> <fault_slice>` |

`EV='sched_process_exec'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 60 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a 60 s slice that starts at it (programs start rarely).
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. List programs started per container that are new. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 60 $WORK/xb.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 60 $WORK/xf.txt $EV
new_programs.py $WORK/xb.txt $WORK/xf.txt
```

One row per container and one VERDICT line listing the new programs.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `new` | the tool reads NEW PROGRAMS IN A CONTAINER | `VERDICT: NEW PROGRAMS IN A CONTAINER ...` | go to `report` Root cause **confirmed** (`unexpected_exec`). |
| `none` | the tool reads NO NEW PROGRAMS | `VERDICT: NO NEW PROGRAMS ...` | **Stop.** No new program in any container. Not this fault. Root cause **rejected**. |

### Report

fault_type: unexpected_exec. The container and programs on the verdict line. Treat the container as compromised: keep it for analysis, redeploy from a clean image.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** (the same 8 programs); reversed quiet.
- **Quiet on the other 15 group-4 runs.**
- **Injected through `docker exec`**: the shell's parent is the container runtime, not the service. The tool does not use the parent.
- **A 60 s baseline is short**: a program that runs once every few minutes in normal operation would look new.
- **Not yet run on the earlier runs.**
