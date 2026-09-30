# Paper Context: From General Agents to RCA Experts — A Self-Evolving Harness for Root Cause Analysis (OpsHarness)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **The most architecturally relevant paper to `agentic-rca/` in the whole set.** Its central
> claim is that **purpose-built RCA agents now lose to general agents**, and that the work should
> go into the *harness* instead. That is an argument about what our repo should be. §7 takes it
> seriously, including where it disagrees with [[beyond-fault-localization]].

---

## 1. Bibliographic info

- **Title:** From General Agents to RCA Experts: A Self-Evolving Harness for Root Cause Analysis
- **Authors:** Haiyu Huang, Zhihan Jiang, **Michael Lyu** (CUHK); Jiewei Lyu (independent);
  Jinyang Liu, Xiao He, Tieying Zhang, Wu Xiang (**ByteDance**)
- **Status:** preprint (recent)
- **System:** OpsHarness

```bibtex
@misc{huang2026opsharness,
  title  = {From General Agents to {RCA} Experts: A Self-Evolving Harness for Root Cause Analysis},
  author = {Huang, Haiyu and Lyu, Jiewei and Jiang, Zhihan and Liu, Jinyang and He, Xiao and Zhang, Tieying and Xiang, Wu and Lyu, Michael},
  note   = {preprint}
}
```

---

## 2. One-paragraph summary

SREs automate RCA either by **pointing a general coding agent** (Codex, Claude Code) at the problem
or by **building a specialised RCA agent**. The authors measure both across **four backbone models
and two public benchmarks** and find the **general agent wins on every backbone** — 36.1% average
top-1 against 17.9% for RCA-Agent and 5.6% for mABC. Their conclusion: the bottleneck is not the
agent, it is **the harness** — the external layer that adapts a general agent to the domain. They
build **OpsHarness**, which **self-evolves**: it contrasts successful and failed trajectories,
distils them into **atomic proposals**, and verifies them before adopting. **59.0% top-1 accuracy,
+63.4% over a bare general agent and 4.02× over baseline RCA agents.**

---

## 3. The measurement that motivates it

**Top-1 accuracy, general agent framework vs specialised RCA agent** (their Table I):

| Backbone | Framework | OpenRCA | RCAEval | **Overall** |
|---|---|---|---|---|
| **GPT-5.5** | **Codex** | 44.9 | **57.4** | **51.2** |
| GPT-5.5 | RCA-Agent | 31.8 | **1.9** | 16.8 |
| GPT-5.5 | mABC | 7.6 | 11.1 | 9.4 |
| Claude Sonnet 4.6 | Claude Code | 25.9 | 27.8 | 26.8 |
| Claude Sonnet 4.6 | RCA-Agent | 26.4 | 5.6 | 16.0 |
| GLM-5.2 | Codex | 46.1 | 46.3 | **46.2** |
| GLM-5.2 | RCA-Agent | 36.8 | 11.1 | 24.0 |
| DeepSeek-V4 | Codex | 20.2 | 20.4 | 20.3 |
| DeepSeek-V4 | RCA-Agent | 28.0 | 1.9 | 14.9 |

**Averages: general agent 36.1%, RCA-Agent 17.9%, mABC 5.6%.**

**The gap is widest on RCAEval** — the benchmark **RCA-Agent was not designed for** — where it
**drops to 5.1%** while the general agent **holds at 38.0%**. Concretely: **bare Codex answers 45%
of OpenRCA queries against RCA-Agent's 32%, on RCA-Agent's own benchmark.**

**Their explanation:** a good RCA agent *"also depends on the general abilities that flagship agent
frameworks have spent years maturing — context management over long-horizon tasks, multi-round
planning, and reasoning."* OpenRCA's own analysis of RCA-Agent shows **many failures stem from
gaps in general agentic competence**, not RCA-specific ones.

**But general agents are not good enough either:** Codex (GPT-5.5) averages only **51.2%** on the
test datasets.

---

## 4. Design

**Two planes.**

**Data plane** — **four tiers of operational knowledge**, each with its own disclosure and update
policy:

| Tier | What it holds |
|---|---|
| **K0** | **general knowledge about the RCA process** — what a diagnosis should do and produce. Ships with the harness as text in root documents (**`AGENTS.md` or `CLAUDE.md`**), loaded every diagnosis |
| **K1** | **a profile of the target system** — schema, on-disk layout, component inventory. Produced automatically by `setup`, read in full at the start of each diagnosis. **It replaces a per-dataset adapter**: it tells the agent how to read this system with no hard-coded loader |
| **K2, K3** | **mined from diagnosis trajectories during evolution** — together, the system's **diagnostic knowledge network** |

The knowledge network is a **directed graph G = (O, E, R)**: **operations are nodes**, an edge
(o, o′) records that **o′ is a sensible next move after o on this system**, and each rule in R is a
**typed annotation on a diagnostic state**. They describe it as *"the automated counterpart of the
expertise an SRE accumulates over a system."* Plus an **idea-card tool library**.

**Control plane** — four workflows: **setup, diagnose, evolve, verify**. **Evolve and verify form
the self-evolution loop**, advancing the harness from one version to the next. During evolution it
**contrasts successful and failed trajectories, converts their evidence into atomic proposals**,
and verifies them.

**Related context they give:** external harnesses already exist in the *Dev* domain — **Superpowers**
(an agentic skills framework) and **OMX** (a workflow layer for Codex) — *"However, in the Ops
domain, such external harnesses are still largely missing."*

---

## 5. Results

- **59.0% top-1 accuracy** across two public benchmarks (**OpenRCA** and **RCAEval**) plus an
  industrial deployment.
- **+63.4% over a bare general agent.**
- **4.02× over baseline RCA agents.**

---

## 6. What kind of paper this is

- A **harness architecture** with a self-evolution loop, evaluated on public benchmarks and in
  industry (ByteDance / "Company A").
- Telemetry is whatever the benchmarks provide — **metrics, logs, traces**. **No kernel data.**
- The central contribution is **an argument about where the engineering should go**, backed by a
  cross-model comparison.

---

## 7. What this means for our work

**This paper is about the thing we built, and it is worth reading our own design against it.**

### The uncomfortable question it poses

Their Table I says **specialised RCA agents lose to general agents, badly, and generalise worst of
all** — RCA-Agent drops from 31.8% on its own benchmark to **1.9%** on RCAEval. **`agentic-rca/` is
a purpose-built agent.** So: is our harness a specialised agent that will not generalise, or is it
the *harness layer* they advocate?

**Mostly the latter, and here is the honest accounting:**

| OpsHarness component | Ours |
|---|---|
| **K0** — general RCA process knowledge in `CLAUDE.md`/`AGENTS.md` | our plan/work/review/synthesise prompts |
| **K1** — auto-generated profile of the target system, **replacing a per-dataset adapter** | **we have a hard-coded loader.** `ctf_tool.py` and `codetool.py` know our run layout |
| **K2/K3** — diagnostic knowledge mined from trajectories | **our blueprints — but hand-written from measurement, never mined** |
| **Idea-card tool library** | `ctf_lines`, `run_python`, `note_finding` |
| **Evolve + verify loop** | **nothing** |

**Two gaps are real.** We have no self-evolution, and our system knowledge is compiled into tools
rather than produced as a readable profile. **Neither is obviously wrong for us** — our blueprints
are *evidence-first by policy*, and mined knowledge would violate that unless verified. **But their
`verify` workflow is exactly the mechanism that would let mining coexist with our rule**: propose
from trajectories, verify against data, then adopt. That is a design we do not have and could.

### The disagreement with Beyond Fault Localization

**These two recent papers contradict each other on the most important question:**

| | Claim |
|---|---|
| **OpsHarness** | the **harness** is the bottleneck; a good one gains **+63.4%** over a bare agent |
| **[[beyond-fault-localization]]** | the **model** is the bottleneck; frameworks span **2.0 pp** under one model, while a model swap gains **10.8 pp** |

**They are not straightforwardly reconcilable**, and both are preprints. Possible resolution:
Beyond-FL compares *existing* frameworks, which may all be thin wrappers; OpsHarness compares
*bare agent vs engineered harness*, a bigger difference. **We should note the disagreement rather
than cite whichever suits us**, and it is a reason to report our own model-vs-harness ablation if
we ever run one.

### The one number to hold onto

**Codex on GPT-5.5 reaches 51.2% average, and OpsHarness reaches 59.0%.** These are the current
numbers for RCA from metrics/logs/traces on public benchmarks. **Our per-family results are on a
different task with different inputs and are not comparable** — but the order of magnitude is
useful context for what "good" currently means in this area, and it is far from solved.

### A small thing worth copying immediately

**K1 replacing a per-dataset adapter.** Their `setup` workflow produces a readable profile —
schema, layout, inventory — that the agent reads at the start of every diagnosis, *"without any
hard-coded loader."* Our tools hard-code the run layout. **Generating a per-run profile
(`pid_ns` inventory, container names, available tracepoints, event counts, clock anchors) and
handing it to the agent up front would be cheap**, and it would make the harness portable to Train
Ticket and to any future dataset without touching tool code.

---

## 8. Safe claims

- SREs automate RCA either by using a **general-purpose agent** or by **building a specialised RCA
  agent**; the authors measure both across **four backbone models** (GPT-5.5, Claude Sonnet 4.6,
  GLM-5.2, DeepSeek-V4) and **two public benchmarks** (OpenRCA, RCAEval).
- **The general agent wins on every backbone**: **36.1% average top-1** against **17.9%
  (RCA-Agent)** and **5.6% (mABC)**.
- **Bare Codex answers 45% of OpenRCA queries against RCA-Agent's 32%** — on RCA-Agent's own
  benchmark.
- **The gap is widest where the specialised agent must generalise**: RCA-Agent drops to **5.1%** on
  RCAEval while the general agent holds at **38.0%**.
- Their explanation: good RCA depends on **general agentic abilities** — long-horizon context
  management, multi-round planning, reasoning — and **OpenRCA's own analysis attributes many
  RCA-Agent failures to gaps in general agentic competence**.
- **General agents are still not sufficient**: Codex (GPT-5.5) averages **51.2%**.
- OpsHarness organises knowledge in **four tiers**: **K0** general RCA process knowledge shipped in
  `AGENTS.md`/`CLAUDE.md`; **K1** an auto-generated **profile of the target system** that
  **replaces a per-dataset adapter**; **K2/K3** mined from trajectories into a **directed graph of
  operations, next-move edges and typed rules**.
- Control plane: **setup, diagnose, evolve, verify**, with **evolve + verify forming a
  self-evolution loop** that contrasts successful and failed trajectories into **atomic
  proposals**.
- External harnesses exist in the Dev domain (**Superpowers**, **OMX**) but *"in the Ops domain,
  such external harnesses are still largely missing."*
- **59.0% top-1 accuracy**, **+63.4% over a bare general agent**, **4.02× over baseline RCA
  agents**, across two public benchmarks and an industrial deployment.

## 9. Do NOT claim

- That its accuracy is comparable to ours. **Different benchmarks, metrics/logs/traces telemetry,
  different task definition.**
- That "specialised agents are bad" is settled. The comparison is against **two specific
  specialised agents** (RCA-Agent, mABC) on **two benchmarks**, in a preprint.
- That the harness matters more than the model. **[[beyond-fault-localization]] measures the
  opposite** (2.0 pp across frameworks vs 10.8 pp across models). Note the disagreement.
- That self-evolution is validated independently. The **+63.4%** is the whole system; the paper's
  ablation would need checking before attributing the gain to evolution specifically.

## 10. Reusable ideas

- **Put the engineering in the harness, not the agent.** Their argument — that flagship frameworks
  have spent years on context management and planning that you will not reproduce — is convincing
  and applies to us.
- **A generated system profile beats a hard-coded loader.** K1 makes the harness portable; ours is
  compiled into the tools.
- **Propose from trajectories, then verify before adopting.** This is how mined knowledge could
  coexist with our evidence-first rule.
- **Contrast successful *and* failed trajectories.** Most self-improvement loops only learn from
  success; the failures carry the discriminating information.
- **Test generalisation to a benchmark you did not design for.** RCA-Agent going 31.8% → 1.9% is
  the single most informative cell in their table, and our `conn_pool_exhaustion` signature not
  transferring to Train Ticket is the same kind of finding.
