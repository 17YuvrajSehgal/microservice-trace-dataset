# Phase 1 result: how much of an agent run goes to the model

Answers Naser's "give a number like >=80% goes to the model," and resolves
the paper's one caveat (that "event-loop wait" mixed LLM-wait with idle).
From the kernel traces we already have (Claude Code) --- no new runs.

## Method (trace only)

Per run: find the API sockets (fds the agent `connect()`ed to on port 443;
all went to one Anthropic IP), pair syscall `entry(fd)` -> `exit(ret)` per
thread to get outgoing requests (`write`/`sendto`) and incoming responses
(`read`/`recvfrom`, `ret>0`). A request is "in flight" from its first write
until the last streamed response read before the next request (the API
*streams* tokens, so the model is working for the whole span). Union those
intervals across all API sockets = wall-clock time with a model request
outstanding. Script: `llm_wait.py`.

## Result

**Uncapped (adequate machine), medians over $n{=}10$ runs, both tasks:**

- **~84% of wall-clock time has an LLM request in flight** (per-run range
  80--91%).
- Local computation is only **~4.7 CPU-seconds** per run.

So on an adequate box the agent is overwhelmingly LLM-bound: ${\ge}80\%$ of
its time is spent waiting on the model, and almost none on the CPU.

**The share shrinks as the CPU cap tightens** (median model-% of wall):

| cpu.max | bug-fix | implement |
|---|---|---|
| uncapped | 88% | 81% |
| 1 core   | 92% | 80% |
| 0.5 core | 79% | 69% |
| 0.25 core| 71% | 53% |

Figure: `figures/fig_llmshare.pdf`. This is the regime story made
quantitative: under a tight cap the OS (CFS throttle) eats wall time that
used to be the model, so the model's share falls from ~80% to ~50--70%.

## Why this needs tracing (for the discussion)

No timing counter can produce these numbers. `cpu.stat` tells you *that* the
cgroup was throttled and for how long; the wall clock tells you the run got
slower. Neither can say *what the agent was waiting on*. Attributing 84% of
wall specifically to the model's socket --- and showing that share drop to
53% under a cap --- requires per-file-descriptor system-call attribution
from the trace: which fd was the API connection, when a request was sent,
when the response streamed back. That is the point of tracing over counters:
counters measure *that/how much*; the trace measures *what and where*.

## Suggested sentences for the paper

> On an unthrottled machine the agent spends a median of 84\% of its
> wall-clock time with a request outstanding to the model and only
> ${\approx}4.7$ CPU-seconds computing locally --- it is almost entirely
> LLM-bound. Tightening the CPU cap does not change how long the model
> takes; it adds throttle wait, so the model's share of wall falls from
> ${\approx}84\%$ (uncapped) to ${\approx}53\%$ at a quarter core. The
> operating system, not the model, now owns half the wall clock.
