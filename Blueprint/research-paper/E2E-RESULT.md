# #3 result: a realistic coding task under CPU, memory, and disk limits

Answers Mahsa's review point #3 ("use a repository task where the agent
changes code and runs tests; compare unlimited with CPU/memory/disk limits;
report total time and task success"). Task = the implement coding task (edit
code + run tests). Both agents. Total completion time (wall, from clock
anchors) and success (task_check). CPU + unlimited reused from Problem 1;
memory and disk are new (3 reps each). Data: `runs_e2e_cl/`, `runs_e2e_cx/`.

## The headline: only CPU bites a lightweight coding task

For a bug-fix/implement task the agent does little local compute and almost
no disk I/O, so the memory and disk caps that cripple the stress workloads
of Problems 3--4 barely touch it. Only the CPU cap slows it, and the memory
cap matters only when the agent process itself no longer fits.

## Claude Code (node), implement task, medians, $n{=}3$

| limit | total time (s) | success | note |
|---|---|---|---|
| unlimited | 21 | 3/3 | baseline |
| CPU 0.25 core | 33 | 5/5 | +75\% (from Problem 1) |
| memory $\ge$192\,MiB | 20--26 | 3/3 | no effect (\texttt{high} events = 0) |
| memory 128\,MiB | 149 | 1/3 | 7x slower, thrashes, 6 OOM kills |
| memory 96\,MiB | 656 | 0/3 | 30x slower, OOM, task fails |
| disk 50 / 20\,MB/s | 23--25 | 3/3 | no effect (I/O-light task) |

- The real coding agent survives down to ${\approx}192$\,MiB by reclaiming
  page cache, then falls off a cliff: at 128\,MiB it thrashes (6 OOM kills
  across 3 runs) and mostly fails; at 96\,MiB it is 30x slower and fails
  every time. The cliff is the agent's own footprint (node, ${\approx}190$
  MiB), not a synthetic allocation.
- Disk caps down to 20\,MB/s have no measurable effect.

## Codex CLI (Rust), implement task, medians, $n{=}3$

Codex **survived every condition, including 96\,MiB** (0 OOM): the lean Rust
binary fits where node cannot. Its wall times are dominated by OpenRouter
API latency (baseline ${\approx}220$\,s, highly variable) and are not
comparable to Claude's, so we report Codex by \emph{outcome} (all succeed),
not by time. This reinforces the cross-agent finding: the memory cliff
tracks the agent's own footprint---Claude (node) dies below ${\approx}190$
MiB, Codex (Rust) survives past 96\,MiB.

## Agent behavior under pressure (feeds review point #4)

Two distinct regimes, both from the kernel + the agent logs:

1. \textbf{Tool OOM, agent survives.} When only a tool exceeds the cap (the
   synthetic 512\,MB anon workload at \texttt{memory.max}=640\,MB), the OOM
   killer takes the \emph{worker}; the agent detects the SIGKILL (exit 137),
   \emph{reports the correct reason} (``typically the kernel's
   out-of-memory killer, but I haven't checked''), does \emph{not} retry,
   and completes its turn with a failure report.
2. \textbf{Agent OOM, agent dies.} When the container is too small for the
   agent itself (128/96\,MiB), node is in the kill path: it thrashes,
   spawning processes that are killed repeatedly (6 OOM kills at 128\,MiB),
   for minutes, and is finally killed with no clean report (the agent log is
   empty). There is no graceful degradation---the agent simply dies.

## What this adds to the paper

- Ecological validity: the mechanisms of Problems 1--4 are real, but a
  \emph{lightweight} coding task only triggers the CPU one; memory/disk bite
  only when the workload stresses them (heavier builds, data processing) or
  when the cap is below the agent's own footprint.
- A realistic, dramatic failure mode: a container under ${\approx}190$ MiB
  does not just slow the agent, it kills it mid-task.
