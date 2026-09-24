# StrataTrace — one-page brief
**Ciena meeting, 24 September 2026**

## What we are building

A labelled observability dataset and a way to measure what telemetry is actually worth
collecting. Four modalities — metrics, logs, distributed traces, kernel traces — captured from
two microservice applications under known, injected faults. Then we give an automated agent a
*subset* and measure what it can still work out.

**The question it answers:** which telemetry do you need to diagnose which failures?

## Where we are

**720 scored runs, two applications, six fault families, zero failures.** This phase gave the
agent **kernel traces only** — no metrics, no logs, no spans — and did not tell it that an
incident happened, when, or where.

| | found the right component |
|---|---|
| host-wide faults (CPU, network, noisy co-tenant) | **40–55 of 60** |
| faults inside one service | **0–3 of 60** in five of six cells (a slow datastore is 24) |

The same split on two applications that share no code.

## The finding that changed our reading

We took "0 of 60" as evidence that kernel traces cannot localise a per-service fault. **It was
not.** It was three layers of our own plumbing:

1. A reply cap truncated tool results mid-JSON. The list naming already-running containers
   reached the model in **4.7%** of calls.
2. The diagnostic playbook reasoned about network *interfaces*, which a kernel trace cannot map
   to a service.
3. The answer schema asked for "a process name" — and several services run as `java`.

The signal was always present: in six of six incidents, the injected container's traffic
collapses to **9–18%** of its own baseline while the median container holds at 63–129%.

After fixing all three, on Sock Shop:

| | with playbook | without |
|---|---|---|
| service network fault, right container | **10 of 30** | 1 of 30 |
| service CPU cap, right container | **6 of 30** | 1 of 30 |

Not solved. Moved off zero, for a reason measured before it was written down.

## Three results we would rather not have

- **A playbook can make an agent worse.** If its deciding check is a threshold on a quantity the
  deployed tools cannot compute, the agent abstains — even when the signal is plainly visible.
- **Ranking by "what degraded most" finds victims, not culprits.** When one service stalls the
  whole application slows, and everything else degrades harder than the faulty component.
- **One of our own injections never engaged.** A CPU cap set fifty times above what the service
  uses. The agent now correctly reports "no fault" in 43 of 60 runs — and our metric scores that
  as failure. Both the injection and the metric need fixing.

## What we would like from you

- **Do these fault families match what you actually see in production?**
- **Which modalities are expensive for you to collect and retain?** That decides which ablation
  we run next.
- **Would you validate the catalogue against your own incidents,** or share anonymised traces?

## Reproducibility

Every prompt, raw model response, tool result and line of agent-written code is recorded, with a
hash of the system prompt. Ground truth is readable only by the scorer — never by anything the
agent can reach. The code sandbox is never given a run directory, because ground truth lives
inside one; 19 adversarial escape attempts, all blocked.

**Target:** MSR 2027 — Data & Tool Showcase plus a study paper. Abstract 5 November 2026.
