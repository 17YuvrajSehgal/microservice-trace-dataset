# Collection scripts — "OS noise for agentic AI"

How we collect the data for the four-problem catalogue (and the realistic
end-to-end test). What each experiment measures and why: see the per-problem
`PLAN.md` files under `Blueprint/latency/*/`.

## The big picture (data flow)

```
vm_setup_agentic.sh         one-time: install LTTng, smoke-test tracing
        │
run_campaign_*.sh           loop over conditions x reps (shuffled, resumable)
        │  calls once per run
        ▼
collect_agent_run.sh ──uses──► tasks/*.sh      (what the agent is told to do)
        │  produces
        ▼
~/runs<...>/<name>/{ trace/, agent.log, meta/ }
        │  read by
        ▼
analysis/analyze_run.py     one run  ->  time budget (per-thread states)
        │  medianed by
        ▼
analysis/aggregate*.py      per-condition medians  ->  tables / figures
```

**Two files are the real substance — read them carefully; skim the rest:**
`collect_agent_run.sh` (how one run is produced) and
`../analysis/analyze_run.py` (how one run becomes numbers).

## Reading order (to understand the work)

1. **`vm_setup_agentic.sh`** — the environment. Installs LTTng 2.15 and
   proves kernel tracing works with a 3-second smoke trace.
2. **`collect_agent_run.sh`** ★ — one run, start to finish: regenerate a
   fresh task repo; create a cgroup and set one resource limit; start the
   LTTng kernel trace; snapshot the cgroup counters *before*; run the agent
   **inside the cgroup**, timed; stop the trace; snapshot counters *after*;
   record success + clock anchors. Every design decision lives here.
3. **A task or two** — `tasks/t3_implement.sh` (a real coding task), then
   `tasks/t4_parallel.sh` (a synthetic one). See the table below.
4. **The `run_campaign_*.sh`** — thin loops over conditions x reps; one per
   experiment (table below).
5. **`../analysis/analyze_run.py`** ★ — rebuilds the agent's process subtree
   from `root.pid` via `sched_process_fork`, then a per-thread state machine
   over `sched_switch`/`sched_wakeup` labels every slice of time as on-CPU,
   runnable-but-waiting (CPU noise), or blocked-on-a-named-syscall; adds the
   memory/IO metrics; validates against the cgroup counters.
6. **`../analysis/aggregate.py`** — medians per condition (Problem 1). Other
   problems aggregate in their own folders (see "Analysis" below).

## Files

### Collector and setup
| file | role |
|---|---|
| `vm_setup_agentic.sh` | one-time VM setup (LTTng + smoke trace). Agent sign-in is manual, after this |
| `collect_agent_run.sh` | ★ ONE run (see signature below) |

### Tasks (what the agent does each run)
| task | role / experiment |
|---|---|
| `t1_toy` | throwaway smoke test (one bug, ~10 s) |
| `t2_medium` | **bug-fix** coding task (3 modules, seeded bugs + tests) |
| `t3_implement` | **implement** coding task (stubs + docstrings + tests) |
| `t4_parallel` | N parallel CPU workers (Problem 2, threads vs cores) |
| `t5_subagents` | launch N sub-agents via the Task tool (Problem 2B) |
| `t6_memtouch` | read a 1 GB file K times (Problem 3, memory/refault) |
| `t7_memhog` | allocate + touch anonymous memory (Problem 3, OOM cliff) |
| `t8_ioread` | cold 1 GB single read (Problem 4, disk I/O) |

Every task regenerates a byte-identical repo, writes a fixed `.prompt`, and a
`.check` that decides success. Workers tag their kernel comm (`ttworker` /
`ttmem` / `ttio`) via `prctl` so the analyzer can find the workload phase.

### Campaigns (loop collect_agent_run over a grid)
| campaign | experiment | grid |
|---|---|---|
| `run_campaign.sh` | Problem 1, CPU cap | t2+t3 x {max,1,0.5,0.25 core} x reps |
| `run_campaign_t4.sh` | Problem 2A, threads | W in {2,4,8,16} x reps |
| `run_campaign_t5.sh` | Problem 2B, sub-agents | N in {4,8} x reps |
| `run_campaign_t6.sh` | Problem 3, memory | `memory.high` (PART=A) or `memory.max` (PART=B) sweeps |
| `run_campaign_t8.sh` | Problem 4, disk I/O | `io.max rbps` in {unltd,200,100,50 MB/s} x reps |
| `run_campaign_e2e.sh` | Realistic end-to-end | coding task under memory + disk sweeps |

All campaigns are shuffled, resumable (skip existing run dirs), and write a
`manifest.csv`. The Problem-3 OOM cliff (t7) was run by a short inline loop,
not a dedicated campaign script (see progress notes 13-10-2026).

## `collect_agent_run.sh` signature

```
AGENT=claude|codex  RUNS_DIR=~/runs  \
  bash collect_agent_run.sh <run_name> <cpu.max> <task.sh> [task_arg] [mem_limit] [io_limit]
```
- `cpu.max`: `max`, or `"<quota> <period>"` e.g. `"25000 100000"` (0.25 core).
- `task_arg`: passed to the task as `TASK_ARG` (e.g. worker count W, file MB).
- `mem_limit`: `high:<N>` or `max:<N>` (sets `memory.high`/`memory.max`;
  also drops page cache so a file read faults in-cgroup).
- `io_limit`: `rbps:<N>` bytes/s (sets `io.max`; enables the `io` controller).
- `AGENT=codex` runs `codex exec` (OpenRouter key in `~/.codex-env`);
  default is Claude Code (`claude -p`).

Example single run: `bash collect_agent_run.sh t2_cap50_r1 "50000 100000" t2_medium.sh`

## Output per run (`~/runs<...>/<name>/`)

- `trace/` — raw CTF kernel trace (decode with babeltrace2).
- `agent.log` — the agent's transcript.
- `meta/` — `ground_truth.json` (agent/exit/success/limits/kernel),
  `cpu.stat`/`memory.*`/`io.stat` before+after, `clock_anchors.jsonl`,
  `root.pid`, `lttng_enabled.txt`, `agent_diff.txt`, `task_check.txt`.
Plus `manifest.csv` at the campaign root.

## Analysis (where one run becomes numbers)

- `../analysis/analyze_run.py` — ★ one run -> time budget (shared by all).
- `../analysis/aggregate.py` — Problem 1 medians.
- per-problem aggregators: `2_threads_vs_cores/analysis/aggregate_t4.py`,
  `3_memory_cap/analysis/aggregate_mem.py`, `4_io_cap/analysis/aggregate_io.py`.
- paper numbers: `research-paper/llm_wait.py` (the 84% LLM-bound metric),
  `compare_agents.py` (Claude vs Codex), `make_data.py` / `make_fig_*.py`.

## Deploy to the VM

```bash
# tar + scp (pscp chokes on a bare directory):
tar czf collection.tgz collection
gcloud compute scp collection.tgz aylabsltd@agentic-noise:collection.tgz \
  --project=teleeporter --zone=us-east1-d
gcloud compute ssh aylabsltd@agentic-noise --project=teleeporter --zone=us-east1-d \
  --command="tar xzf collection.tgz && find collection -type f -exec sed -i 's/\r$//' {} +"
```

## Known gotchas (do not rediscover)

- cgroup-v2 delegation: a non-root process cannot move its own PID into the
  cgroup — the collector writes `cgroup.procs` via sudo, capturing the
  subshell's `BASHPID` first (`echo $BASHPID | sudo tee` would report the
  pipe-subshell's pid and the agent would never enter the cgroup).
- The agent runs in a subshell placed into the cgroup; the parent stays
  outside so lttng/sudo teardown is not charged to the agent's counters.
- `cpu.stat` is cumulative and cannot be zeroed, so the cgroup is recreated
  each run (counters start at ~0).
- Memory runs drop the page cache first, so a file read faults in *inside*
  the capped cgroup (otherwise `dd`'s cache in the root cgroup is hit for free
  and the cap never bites).
- The `io` controller is not in the root `subtree_control` by default — the
  collector enables `+io` before setting `io.max`.
- Kernel tracepoint names are `mm_vmscan_*`, not `vmscan_*`; the wrong
  wildcard records nothing (reclaim invisible).
- Workers set their comm to `ttworker`/`ttmem`/`ttio` via `prctl` because the
  shebang makes comm `python3`, which collides with the agent's own python3.
- LTTng's consumer writes the trace dir as root — the collector chowns it back.
- The agent must be signed in for the user running the scripts: Claude Code
  needs `~/.claude*`; Codex needs `~/.codex/config.toml` + `~/.codex-env`.
