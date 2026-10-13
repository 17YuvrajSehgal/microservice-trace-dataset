# Phase 2 result: the findings hold on a second agent (Codex)

Answers Naser's "if we can do another agent and show the results are
consistent, it would be a better paper." We re-ran the CPU-cap experiment
with **Codex** (OpenAI Codex CLI, model `openai/gpt-6-luna` via OpenRouter)
--- a completely different harness from Claude Code: a Rust/tokio binary,
a different model, a different API endpoint.

## Setup

Same VM, same byte-identical tasks, same cgroup method. The collector takes
an `AGENT=claude|codex` switch; Codex runs headless via
`codex exec --dangerously-bypass-approvals-and-sandbox`. Implement task,
4 caps x 3 reps = 12 Codex runs, all solved (agent_exit=0, task_check=0, no
test tampering). Analyzer is agent-agnostic (subtree from fork); on-CPU
validated 91% vs `cpu.stat`.

## Result: consistent across agents

Medians (Claude $n{=}5$, Codex $n{=}3$), implement task:

| cpu.max | throttle (Claude / Codex) | model-\% wall (Claude / Codex) |
|---|---|---|
| uncapped | 0.0 / 0.0 s | 81\% / 89\% |
| 1 core   | 0.45 / 0.2 s | 80\% / 88\% |
| 0.5 core | 6.3 / 3.6 s | 69\% / 79\% |
| 0.25 core| 19.8 / 19.4 s | 53\% / 52\% |

Figure: `figures/fig_consistency.pdf`.

- **Same throttle ladder**: both agents go 0 $\to$ tenths $\to$ a few $\to$
  ${\sim}20$ s as the cap tightens; the curves nearly overlap and converge
  at 0.25 core.
- **Same regime shift**: both are ${\ge}80\%$ LLM-bound uncapped (Claude
  81\%, Codex 89\%) and both drop to ${\approx}52\%$ at a quarter core as
  throttle fills the wall. The model's share is measured independently per
  agent (each agent's own API socket), yet they agree.
- Differences are second-order: Codex uses a bit less local CPU
  (${\approx}3.5$ vs ${\approx}5$ CPU-s --- Rust vs node) and is slower per
  turn (OpenRouter/gpt-6-luna), so its absolute walls are larger, but the
  trends are identical.

## Why only the CPU cap needed re-running

Problems 2--4 (threads-vs-cores, memory, disk I/O) are **agent-independent
by construction**: their workloads are fixed worker processes launched by
the task scripts (`run_all.sh`, etc.), so those metrics measure the
workload, not the agent --- any agent that runs the script produces the same
numbers. Only the CPU cap and the LLM-share depend on the agent's own
behavior, so those are what we cross-check. Codex ran those workloads too
(the smoke runs), confirming it executes them like Claude.

## Suggested sentences for the paper

> To check that these effects are a property of agentic workloads and not of
> one harness, we repeated the CPU-cap experiment with a second, unrelated
> agent (Codex CLI, a Rust binary driving a different model through a
> different API). The results are consistent: both agents are ${\ge}80\%$
> LLM-bound on an unthrottled machine, and both show the model's share of
> wall fall to ${\approx}52\%$ at a quarter core as CFS throttle takes over.
> The throttle curves nearly coincide (Figure~\ref{fig:consistency}).
