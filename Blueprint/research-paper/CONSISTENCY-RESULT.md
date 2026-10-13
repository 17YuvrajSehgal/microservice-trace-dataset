# Phase 2 result: the findings hold on a second agent (Codex)

Answers Naser's "if we can do another agent and show the results are
consistent." We replicated **all four problems** with **Codex** (OpenAI
Codex CLI, `openai/gpt-6-luna` via OpenRouter) at full parity with the
Claude campaign --- a completely different harness (Rust/tokio binary,
different model, different API).

## Scale

**130 Codex runs**, matching the Claude design 1:1: CPU cap (t2+t3 x 4 caps
x 5), threads (4 W x 5), sub-agents (2 N x 3), memory.high (4 x 5),
memory.max+file (4 x 3), OOM cliff (4 x 3), disk I/O (4 x 5). All solved
(agent_exit=0). Collector took an `AGENT=claude|codex` switch; analyzer is
agent-agnostic (subtree from fork). Raw numbers: `compare_agents.py`,
`analysis_compare_output.txt`.

## Result: consistent across agents on every problem

**Problems 2, 3A, 4 are essentially identical** --- the medians match to
within noise, because these workloads are fixed worker processes the agent
merely launches:

| problem | metric | Claude | Codex |
|---|---|---|---|
| #2 threads (W=8/16) | phase (s) | 1.9 / 3.9 | 1.9 / 3.8 |
| #2 threads (W=8/16) | runnable/wkr (s) | 0.9 / 2.8 | 0.9 / 2.8 |
| #3A mem (1152/768M) | phase (s) | 30.4 / 30.4 | 30.4 / 30.4 |
| #3A mem (1152/768M) | refault (M) | 1.0 / 1.0 | 1.0 / 1.0 |
| #4 io (100/50 MB/s) | phase (s) | 10.1 / 20.4 | 10.2 / 20.4 |

**Problem 1 (CPU cap) and the LLM-share show the same trends** (t3; medians):

| cpu.max | throttle (Cl / Cx) | model-\% wall (Cl / Cx) |
|---|---|---|
| uncapped | 0.0 / 0.0 | 81 / 89 |
| 1 core   | 0.5 / 0.2 | 80 / 88 |
| 0.5 core | 6.3 / 3.6 | 69 / 79 |
| 0.25 core| 19.8 / 18.7 | 53 / 62 |

Both agents are ${\ge}80\%$ LLM-bound uncapped and both shed that share as
the cap tightens (measured independently via each agent's own API socket ---
Codex talks to OpenRouter). Codex is leaner on CPU (${\approx}3.5$ vs
${\approx}5$ CPU-s, Rust vs node) and slower per turn (its walls are larger),
but the mechanism is identical. Figure: `fig_consistency.pdf`.

## One instructive difference: the OOM cliff shifts with the agent

The OOM cliff (Problem 3, anonymous memory) is the one place the agents
differ --- and it is informative, not contradictory:

| memory.max | Claude OOM | Codex OOM |
|---|---|---|
| 768 MB | 0/3 | 0/3 |
| 640 MB | **3/3** | **0/3** |

Same mechanism (unreclaimable memory with no swap triggers an OOM kill),
different **threshold**: the cliff sits at *agent RSS + workload*. Claude
(node, ${\approx}250$ MB RSS) + 512 MB $\approx$ 762 MB, so it dies at
640 MB; Codex (Rust, a much smaller RSS) + 512 MB stays under 640 MB and
survives. The cliff is real for both; its location tracks the agent's own
footprint. (We did not push Codex below 640 MB; its cliff is lower.)

This strengthens the paper: the OOM cliff is not a fixed number but a
predictable function of total footprint, which the cgroup counters and trace
make explicit --- a leaner harness buys headroom.

## Takeaway for the paper

> We replicated all four problems with a second, unrelated agent (Codex CLI,
> a Rust binary driving a different model through a different API), 130 runs
> at parity. The scheduling, memory-reclaim and I/O results are identical ---
> they are properties of the workload under a cgroup limit, not of the
> harness. The CPU-cap and LLM-share results show the same trends on both
> agents (both ${\ge}80\%$ LLM-bound uncapped). The only difference is the
> OOM cliff's position, which tracks each agent's memory footprint: the
> leaner Rust harness survives a tighter cap than the Node one. The effects
> are thus a property of agentic workloads under resource limits in general.
