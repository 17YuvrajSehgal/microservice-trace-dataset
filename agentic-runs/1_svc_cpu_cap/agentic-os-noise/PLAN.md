# OS noise for agentic AI — data collection plan

Date: 2026-10-11. Comes from the 07-10-2026 meeting
(`../../../../meeting-notes/07-10-2026-summary.md`): recreate the CPU-cap problem under
an agentic workload and measure how much of an agent's slowness is the OS,
not the LLM.

## Reframe

We do not inject a fault with stress-ng. The CPU cap **is** the
configuration — the same cgroup `cpu.max` mechanism agent sandboxes already
use. Plus one pure observation condition with no cap at all.

## Question the data answers

Of an agent's total task time, how much is:

- **runnable-but-not-running** (throttled / waiting for CPU),
- vs **waiting on the LLM API**,
- vs **actually computing**?

If the CPU share is non-trivial at realistic sandbox limits, that is the
finding. Even ~5% is a result (Naser, 07-10 meeting).

## Setup

- **Machine**: fresh GCP VM (`git clone --recursive` → `vm_bootstrap.sh`).
  Not Windows/WSL — kernel LTTng needs real Linux, and paper numbers must
  come from a VM anyway.
- **Agent**: Codex CLI (open source, headless) running **inside a Docker
  container**. LLM stays a remote API — we trace the system under the
  agent, not the model. LM Studio local-model comparison = optional later
  phase.
- **Task**: 2–3 fixed coding tasks in a small repo mounted into the
  container, e.g. "make this failing test pass". Same prompt, same model,
  every run.

## Step 1 — Observe first (no cap, no injection)

Run the agent uncapped and just look:

- Does the harness itself create cgroups/limits for its sandbox? Check
  `/sys/fs/cgroup/` for what it spawns, and `cpu.max` in each. (Naser's
  "do the agent tools already do this themselves?" question.)
- How many threads/subprocesses does it spawn vs available cores?
- Baseline time split from the kernel trace: run / sleep / wait-for-CPU.

This alone may show natural OS noise with zero intervention.

## Step 2 — Controlled cap conditions

Per run, set the container's CPU quota (configuration, not a fault):

| condition | cpu.max |
|---|---|
| uncapped | unlimited |
| realistic sandbox | 1 core |
| tight | 0.5 core |
| very tight | 0.25 core |

~5 reps per (task × condition) — LLM nondeterminism makes single runs
noisy. Randomize run order.

## Step 3 — Collection per run (reuse the existing rig)

Wrap in a `collect_trace.sh`-style script:

1. Start a kernel LTTng session with the existing event profile
   (`sched_switch`, `sched_wakeup`, syscalls, `power_cpu_frequency`).
2. Snapshot the container cgroup's `cpu.stat` (`nr_throttled`,
   `throttled_usec`) before and after — cheap ground truth to validate the
   trace analysis against.
3. Launch the agent headless; capture its stdout/log with timestamps
   (per-turn boundaries).
4. Record wall-clock start/end plus the usual clock anchors.
5. Stop, gzip, write ground truth (condition, task, rep) to a manifest.

## Step 4 — Analysis (the `1_svc_cpu_cap/tools` scripts apply directly)

Per run, decompose agent wall time:

- **LLM wait**: agent process blocked in `poll`/`recvmsg` on the API socket.
- **Local compute**: agent + tool subprocesses on-CPU.
- **CPU noise**: runnable-but-waiting + cfs-throttled time (from sched
  events; cross-check against the `cpu.stat` deltas).
- **Other I/O block**.

Headline numbers:

- CPU-noise share of total task time, and of non-LLM time, per cap level.
- Wall-clock task time vs cap — "at 0.5 core the same task takes X%
  longer, and the trace shows exactly why."

## Order of work

1. **Pilot** (~1 day): one task, uncapped, on any Linux box. Confirm we can
   trace the agent and split LLM-wait from local work.
2. **VM campaign**: the full grid (tasks × conditions × reps).

## Open items

- Read the 3 OS-noise papers Naser is sending (CPU-noise one first) before
  locking the noise taxonomy.
- Decide final agent harness (Codex CLI vs Claude Code headless) during the
  pilot.
