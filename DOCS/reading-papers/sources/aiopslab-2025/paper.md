# Paper Context: AIOPSLAB — A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds (MLSys 2025)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **The closest published work to `agentic-rca/` — an agent harness with fault injection, a task
> taxonomy, and scored evaluation.** Its localisation numbers are the ones a reviewer will place
> beside ours, so §8 spells out exactly why they are not comparable and what *is*.

---

## 1. Bibliographic info

- **Title:** AIOPSLAB: A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds
- **Authors:** Yinfang Chen (UIUC), Manish Shetty (UC Berkeley), Gagan Somashekar (Microsoft),
  **Minghua Ma** (Microsoft, corresponding), Yogesh Simmhan (IISc), **Jonathan Mace**,
  Chetan Bansal, Rujia Wang, Saravan Rajmohan (Microsoft)
- **Venue:** MLSys 2025
- Introduces the term **AgentOps**.

```bibtex
@inproceedings{chen2025aiopslab,
  title     = {{AIOpsLab}: A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds},
  author    = {Chen, Yinfang and Shetty, Manish and Somashekar, Gagan and Ma, Minghua and Simmhan, Yogesh and Mace, Jonathan and Bansal, Chetan and Wang, Rujia and Rajmohan, Saravan},
  booktitle = {MLSys}, year = {2025}
}
```

Overlapping author set with [[rcacopilot-2024]] and [[roy-2024-llm-agents-rca]] — this is
Microsoft's AIOps line of work.

---

## 2. One-paragraph summary

A framework that **deploys microservice environments, injects faults, generates workload, exports
telemetry, and scores agents** against ground truth — the same job our `agentic-rca/` harness
does. They define a **four-level task taxonomy** (detection → localisation → root cause analysis →
mitigation), build a fault library across two DeathStarBench applications, and evaluate four
agents: GPT-3.5 and GPT-4 with shell access, **ReAct**, and **Flash**. **Best overall accuracy is
59.32%**, and the per-task numbers fall sharply as the task gets harder: **detection up to 100%,
localisation 46-62% at Acc@1, RCA 36-45%, mitigation 27-55%.**

---

## 3. The task taxonomy — worth adopting as vocabulary

| Level | Task | The question |
|---|---|---|
| **1** | **Detection** | Can the approach accurately detect anomalies or deviations? |
| **2** | **Localization** | Can the approach **pinpoint a fault's exact source (e.g. microservice)**? |
| **3** | **Root Cause Analysis** (2 sub-tasks) | Can it determine the underlying cause? |
| **4** | **Mitigation** | Can it give effective solutions to recover the environment? |

The RCA task has two sub-tasks: **system-level** and **fault-type prediction**.

Their metric for localisation: *"the agent's submission matching the fault microservice's name."*

---

## 4. Environment and fault library

**Applications:** DeathStarBench **SocialNetwork** and **HotelReservation** (Go + gRPC), on
Kubernetes.

**Fault taxonomy:** two kinds —

- **Symptomatic faults** (performance degradation, network loss, pod failure) — used for **Level
  1 and 2** tasks, detection and localisation.
- **Functional faults** (auth revocation, code bugs, scaling errors, bad node assignment) — used
  for **all four** levels.

Ten faults, including:

| # | Fault | App | Levels | Kind |
|---|---|---|---|---|
| 5 | application-level **code bug** in the microservice image | SocialNetwork | 1-4 | Functional |
| 6 | **ScalePod** — incorrect scaling drops a service to zero pods | SocialNetwork | 1-4 | Functional |
| 7 | **AssignNonExistentNode** — pod pending due to wrong node | SocialNetwork | 1-4 | Functional |
| 8 | **NetworkLoss** | HotelReservation | 1, 2 | Symptomatic |
| 9 | **PodFailure** | HotelReservation | 1, 2 | Symptomatic |
| 10 | **Noop** — no fault injected | both | 1 | — |

**288 cases total.** Injection targets vary deliberately — `user-service`, `text-service`,
`post-storage-service` — because *"each service may have distinct dependencies, resulting in
varied fault 'blast radius' or failure propagation topologies."*

They also note honestly that some faults **do not generalise**: Fault 5 is an application-level
code bug baked into an image, and faults 3, 4 need Kubernetes ConfigMap updates and trigger
scripts.

---

## 5. Results

### Overall (Table 3)

| Agent | LoC to register | Time (s) | Steps | Tokens | **Accuracy** |
|---|---|---|---|---|---|
| **Flash** | 60 | 99.64 | 8.48 | 6,484 | **59.32%** |
| **ReAct** | 49 | 43.79 | 11.50 | 16,941 | **55.93%** |
| GPT-4-w-shell | 41 | 28.61 | 6.44 | 6,395 | 49.15% |
| GPT-3.5-w-shell | 41 | 12.44 | 14.70 | 2,558 | **15.25%** |

### By task (Table 4)

| Agent | Detection | **Localization Acc@1** | RCA | Mitigation |
|---|---|---|---|---|
| **Flash** | **100%** | 46.15% | 36.36% | **54.55%** |
| **ReAct** | 76.92% | 53.85% | **45.45%** | 36.36% |
| **GPT-4-w-shell** | 69.23% | **61.54%** | 40.90% | 27.27% |
| GPT-3.5-w-shell | 23.07% | 30.77% | 9.09% | **0%** |
| pDiagnose (non-LLM baseline) | — | 15.38% | — | — |
| RMLAD (non-LLM baseline) | — | **7.69%** | — | — |
| MKSMC (non-LLM baseline) | 15.38% | — | — | — |

**Localisation Acc@3 is higher than Acc@1** for ReAct (69.23% vs 53.85%) and Flash (61.54% vs
46.15%) — they mark those drops explicitly.

**The two non-LLM localisation baselines score 15.38% and 7.69%.**

### Where steps go

- Accuracy **improves with more steps**, Flash peaking at **59.32%** as the step limit rises, then
  **plateauing**. They read the plateau as needing *"(1) better planning, (2) improved feedback
  mechanisms for intermediate steps, and (3) solutions that go beyond environment [interaction]."*
- **Agents waste steps on unnecessary actions** — repeatedly calling the same API, **generating
  non-existent APIs**, and excessive multi-agent chatter. GPT-3.5 *"often generates incorrect API
  commands in loops, leading to repeated errors in execution."*
- Action distribution is dominated by `kubectl get` (23.0%), other `kubectl` (25.6%) and Submit
  (23.5%). Shell commands actually used across all runs are few: ReAct issued `cat` 30 times,
  `ls` 26, `awk` 3, `grep` 1; Flash `cat` 10, `ls` 8, `echo` 3.

---

## 6. What kind of paper this is

- A **benchmark and harness**, plus an evaluation of four off-the-shelf agents.
- Telemetry is **metrics, logs and traces** from a Kubernetes deployment. **No kernel traces.**
- The agent acts through a **shell and Kubernetes APIs**.
- Scoring is **exact-match against the injected fault's service name** and task-specific checks.

---

## 7. What this means for our work

**This is the paper our harness will be compared against, so the comparison should be ours to
frame.** Structurally it is the same idea: deploy, inject, collect, let an agent investigate,
score against ground truth. **Where it differs is the whole point of our work.**

| | AIOpsLab | `agentic-rca/` |
|---|---|---|
| Telemetry | metrics, logs, traces | **kernel traces (LTTng CTF)** |
| Agent's access | **live cluster** — shell + `kubectl`, can act | **recorded run, read-only** |
| Tasks | detection, localisation, **RCA, mitigation** | detection, localisation, fault label, window |
| Apps | DeathStarBench SocialNetwork, HotelReservation | Sock Shop, Train Ticket |
| Faults | 10, mostly **functional** (pod failure, scaling, auth) | **24 families, all performance/resource** |
| Scale | 288 cases | 303 runs |

**Two differences matter most.** First, **their agent operates on a live cluster and can run
`kubectl`** — that is a much stronger information channel than a recorded trace, and it makes
their localisation task easier in one sense (you can ask the orchestrator what is broken) and
harder in another (you must choose actions). **Ours cannot act at all.** Second, **their fault
mix is functional**: a pod at zero replicas, a pod pending on a non-existent node, revoked auth.
Those announce themselves. **Ours are performance faults that, per Waseem, are the ones nobody
files issues about.**

**So the honest framing of our numbers.** We measured `deadlock` at 30/30 and
`conn_pool_exhaustion` at 27/30. Their localisation Acc@1 tops out at **61.54%**. **Those numbers
must not be placed side by side.** Different fault families, different telemetry, different action
space, different scoring rule. What *can* be said is narrower and still worth saying:

> On kernel traces alone, with no application instrumentation and no ability to query the
> orchestrator, an agent can name the responsible container for these fault families. AIOpsLab
> shows that on richer telemetry with live cluster access, general-purpose agents localise
> correctly **46-62%** of the time across a mostly functional fault set.

**Their non-LLM baselines are the useful anchor.** pDiagnose **15.38%** and RMLAD **7.69%** on
localisation. That is the state of pre-LLM automated localisation on their benchmark, and it puts
the LLM agents' 46-62% in perspective.

**Three findings that bear directly on our harness, and two of them we hit independently.**

1. **"Agents waste steps on unnecessary actions ... generating non-existent APIs ... repeated
   errors in execution."** That is exactly the failure our `codetool.py` `_HINTS` and the
   `ctf_tool` actionable error messages were added to fix. **Independent confirmation that the
   problem is general, not our prompt.**
2. **Accuracy rises with the step limit, then plateaus.** We raised `MAX_WORKER_STEPS` from 12 to
   18 and `THREAD_BUDGET` from 80k to 150k on the same reasoning. Their plateau is a caution that
   raising it further has diminishing returns — and their diagnosis (better planning, better
   intermediate feedback) matches our wrap-up-turn fix, which was about **capturing what the
   worker already saw** rather than giving it more room.
3. **Acc@3 exceeds Acc@1 substantially** — ReAct 69.23% vs 53.85%. The right answer is often in
   the agent's candidate set but not ranked first. **Our scoring is Acc@1-equivalent** (one named
   container). Reporting a top-3 variant would be cheap and would make our results comparable to
   theirs on one axis.

**Their taxonomy is better vocabulary than ours and we should adopt it.** Detection → Localisation
→ RCA → Mitigation, with RCA split into system level and fault type. Our axes (WHERE, window,
fault label) map onto Levels 2 and 3, and **we do no mitigation at all** — which is worth stating
as a scope boundary rather than leaving implicit.

**One thing we do that they flag as a problem they did not solve.** They observe that injecting
into different services matters because of *"varied fault blast radius or failure propagation
topologies"* — and they use three injection targets. **Our WHERE scoring already distinguishes
`named` / `container` / `container_wrong` / `scope`**, which is a finer-grained answer to the same
concern.

**A limit on citing their accuracy figures.** 288 cases across 10 faults and 2 applications, with
**Noop** as one of them. Per-task sample sizes are small — the detection table is 13 problems, so
**100% is 13 of 13**, and localisation percentages move in steps of 7.69% (1/13). **Quote these as
indicative, not precise.**

---

## 8. Safe claims

- AIOPSLAB **deploys microservice environments, injects faults, generates workloads, exports
  telemetry, and orchestrates and evaluates agents** — the framework and the benchmark together.
- Four-level task taxonomy: **Detection, Localization, Root Cause Analysis (system level + fault
  type), Mitigation**. Localisation is scored as *"the agent's submission matching the fault
  microservice's name"*.
- Faults split into **symptomatic** (performance degradation, network loss, pod failure — used for
  levels 1-2) and **functional** (auth revocation, code bug, scaling error, bad node assignment —
  used for all levels).
- Applications: **DeathStarBench SocialNetwork and HotelReservation** (Go, gRPC) on Kubernetes.
  **288 cases**, 10 faults including a **Noop**.
- Injection targets are varied deliberately because *"each service may have distinct dependencies,
  resulting in varied fault 'blast radius' or failure propagation topologies."*
- Overall accuracy: **Flash 59.32%, ReAct 55.93%, GPT-4-w-shell 49.15%, GPT-3.5-w-shell 15.25%**.
- By task: **detection up to 100% (Flash)**; **localisation Acc@1 61.54% (GPT-4) / 53.85% (ReAct)
  / 46.15% (Flash)**, with **Acc@3 higher** at 69.23% and 61.54%; **RCA 45.45% (ReAct) max**;
  **mitigation 54.55% (Flash) max, 0% for GPT-3.5**.
- Non-LLM localisation baselines: **pDiagnose 15.38%, RMLAD 7.69%**; detection baseline MKSMC
  15.38%.
- **Accuracy improves with more steps then plateaus**; the authors attribute the plateau to
  needing better planning, better intermediate feedback, and approaches beyond environment
  interaction.
- **Agents waste steps** repeatedly calling the same API, **generating non-existent APIs**, and on
  multi-agent communication; GPT-3.5 *"often generates incorrect API commands in loops."*
- An Amazon outage can cost **$100 million in one hour** (their cited motivation).

## 9. Do NOT claim

- That its accuracy figures are comparable to ours. **Different telemetry (metrics/logs/traces vs
  kernel traces), different action space (live cluster vs recorded run), different fault mix
  (mostly functional vs all performance).**
- That the percentages are precise. Per-task problem counts are small — **detection is 13
  problems**, so each case moves the number by 7.69%.
- That it uses kernel-level data. It does not.
- That Flash is the best agent overall in a general sense. It wins on average and on detection and
  mitigation; **GPT-4-w-shell beats it on localisation Acc@1** and ReAct beats it on RCA.

## 10. Reusable ideas

- **A four-level task taxonomy** — detection, localisation, RCA, mitigation — is better vocabulary
  than our ad-hoc axes, and it makes the scope boundary (we stop before mitigation) explicit.
- **Report Acc@1 and Acc@3.** The gap between them says whether the agent knows the answer but
  ranks it badly, which is a different problem from not knowing.
- **Include a Noop case.** A fault-free problem in the benchmark catches agents that always find
  something.
- **Vary the injection target on purpose**, because blast radius differs by dependency position.
- **Measure steps, tokens and wall time alongside accuracy.** Their Table 3 makes the cost of
  59.32% visible; ours should too.
- **Report the non-LLM baselines.** 7.69% and 15.38% are what makes 46-62% meaningful.
