# Paper Context: FixItFlow — Automated Troubleshooting Guide Generation from Cloud Incidents (arXiv 2026)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **Read section 9 before citing anything from this paper.** Its abstract and conclusion are
> positive, but its own results table shows engineers rated the output poorly: satisfaction
> 2.58/5, **NPS of -100**, and **0% said they would adopt the guides**. The reference pack
> currently cites it for one statistic, which is safe; the rest is not.

---

## 1. Bibliographic info

- **Title:** FixItFlow: Automated Troubleshooting Guide Generation from Cloud Incidents
- **Authors:** Srihari Unnikrishnan (Microsoft Research), Jaskaran Singh Walia (Microsoft
  Research), Drishti Goel (UIUC), Supriyo Ghosh (Inception)
- **arXiv:** 2607.13035v1 [cs.CL], 3 May 2026
- **Length:** 7 pages
- **Venue:** none stated - arXiv preprint

```bibtex
@article{unnikrishnan2026fixitflow,
  title   = {FixItFlow: Automated Troubleshooting Guide Generation from Cloud Incidents},
  author  = {Unnikrishnan, Srihari and Walia, Jaskaran Singh and Goel, Drishti and Ghosh, Supriyo},
  journal = {arXiv preprint arXiv:2607.13035},
  year    = {2026}
}
```

---

## 2. One-paragraph summary

Troubleshooting guides help, but writing them by hand is slow, so coverage is patchy and
content goes stale. FixItFlow generates guides **automatically from past incident tickets**
using an LLM. It ingests resolved incidents that have real engineer discussion, cleans them,
summarises what engineers actually did, clusters recurring scenarios, and writes a guide in a
fixed three-part shape: **Symptom, Diagnosis, Mitigation**. Its main technical idea is an
**anti-hallucination rule**: every command in a generated guide must be an exact
character-for-character copy of something an engineer wrote. If engineers described an action
without showing the command, the guide describes the action and includes no command. In a
survey of 26 engineers the guides scored 3.46/5 on clarity but 2.58/5 on overall satisfaction,
and none said they would adopt them.

---

## 3. Motivation

- Microsoft engineers maintain **over 50,000 TSGs**, used by **more than 60,000 practitioners
  every month** (they cite AutoTSG for this).
- Coverage is inconsistent, quality varies by team, and documents get long and hard to follow
  under pressure.
- **An internal study found the top TSG problems:**

| Problem | Share of complaints |
|---|---|
| Missing information | **32.24%** |
| Broken links | **13.32%** |
| Incorrect instructions | **11.21%** |

Together these are over half of all user complaints about TSG quality. **This is the number
the reference pack cites, and it is the most reusable thing in the paper.**

### Stated contributions

1. A pipeline that generates TSGs from raw incident data with **no pre-existing documentation**.
2. Preprocessing that filters and normalises incident artifacts.
3. Schema constraints and validation to enforce grounding and reduce hallucination.
4. An evaluation with domain experts.

---

## 4. The pipeline

Four stages: **extract → preprocess → semantic analysis → synthesis**.

### 4.1 Ingestion

- **Incremental**: each run stores a checkpoint timestamp and only processes incidents after
  it.
- **Eligibility filter**: an incident must be **resolved** and have **at least six engineer
  comments**. This deliberately excludes auto-resolved and low-signal cases.
- Collects three things per incident: scenario metadata (severity, time, recurrence), the full
  diagnosis thread, and a mitigation summary if present.

### 4.2 Three-stage cleaning

1. **Format cleaning** - strip HTML and markup, but keep code blocks and commands.
2. **Content filtering** - drop bot messages and comments under **25 characters**.
3. **Duplicate removal** - merge related threads into one incident story.

Result: **35-40% less data** with engineer-written technical content preserved.

### 4.3 Extraction

The LLM is framed as a Senior Site Reliability Engineer. Four constraints: a role
specification, **13 predefined content categories**, filters keeping only human contributions,
and a rule that everything extracted must be grounded in the incident data.

The 13 categories: investigation steps, literal commands/queries, diagnostic reasoning, tool
usage, error analysis, service dependencies, timeline analysis, escalation details,
configuration reviews, workarounds and fixes, validation steps, root cause analysis,
prevention measures.

### 4.4 Scale handling

Prioritises **shorter comments first** to cover more distinct incidents, within a **100,000
token** limit.

### 4.5 Output shape

| Section | Contents | Length asked for |
|---|---|---|
| **Symptom** | observable failure signals, detection, impact, timeline, dependencies, monitoring indicators | 2-3 paragraphs |
| **Diagnosis** | investigation strategy, workflow, tool usage, data analysis, exact commands | 3-4 paragraphs |
| **Mitigation** | decision strategy, intervention, risk coordination, verification, prevention | 2-3 paragraphs |

---

## 5. The anti-hallucination protocol (the paper's central idea)

Rules, quoted in substance:

- **Mandatory verification** - before including any command or query, the exact text must be
  found in comments of previous incidents.
- **Literal extraction** - commands copied **character by character**.
- **No inference** - if an engineer describes an action without showing the command, describe
  the action and include **no command**.
- Acceptable: *"Engineer restarted service (command not provided)"*.
- Forbidden: inventing a restart command from the description.

They describe the effect as turning the LLM "from a probabilistic text generator into a
precision-controlled retrieval system".

There is also a **validation checklist** run before including any incident: is there a
three-section narrative, 2-4 paragraphs per section, every command copy-pasted from source, no
invented commands, all Kusto queries found and copied character-by-character.

Commands are tagged by type in the output: `kusto`, `shell`, `text`, `json`.

### Engineering details

- Four sub-stages: comment classification (few-shot) → incident summarisation (parallel) →
  scenario aggregation (LLM similarity clustering) → TSG synthesis.
- **Semaphore-based rate limiting**, dynamic batching, and **exponential backoff with jitter**
  to avoid thundering-herd effects.

---

## 6. Evaluation

Survey of **26 engineers**, plus two interviews.

### Table 1 — per-item satisfaction (5-point scale, Top-2 Box = % rating 4 or 5)

| Item | N | Mean | Top-2 Box |
|---|---|---|---|
| Clarity and understandability | 26 | **3.46** | **61.5%** |
| Logical coherence and flow | 26 | 3.08 | 42.3% |
| Factual accuracy | 26 | 2.92 | 42.3% |
| Document completeness | 26 | **2.62** | 23.1% |
| Overall satisfaction with the synthesis | 26 | **2.58** | 19.2% |
| **Would you adopt this TSG (with minor manual edits)?** | 13 | **0.23** | **0.0%** |

### Table 2 — summary

| Metric | Value |
|---|---|
| Utility Index (mean) | 2.74 |
| Utility Index (Top-2 Box) | 23.1% |
| **NPS** | **-100.0** |

### Interviews

- **Engineer 1** - found it useful but had adoption concerns; wanted headings aligned with
  team templates. Status "Accepted".
- **Engineer 2** - preferred an earlier version (v0.2), citing missing mitigation steps.
  Status "In pipeline".

### The 2.3× claim

The abstract and conclusion state "a 2.3x reduction in mitigation time for incidents with
associated guides". **This is a property of incidents having guides at all**, from their
motivation study of Sev1/Sev2 incidents - it is **not** a measured effect of FixItFlow's
generated guides. The evaluation section contains no timing experiment.

---

## 7. An unsupported comparison

Section 6 says: *"FixItFlow consistently produces higher-quality TSGs compared to using basic
GPT-4o without any special instructions or processing."*

**There is no such comparison anywhere in the paper.** No GPT-4o baseline appears in Table 1 or
Table 2, and no ablation is reported. Treat this sentence as unsupported.

---

## 8. Gaps in the paper itself

1. Section 3.2 promises an analysis of TSG coverage across incidents, then gives no numbers -
   only "there is still room to broaden their reach".
2. No figure showing the TTM correlation the motivation section builds on.
3. No ablation of the anti-hallucination protocol, the cleaning stages, or the clustering.
4. No dataset size. We are not told how many incidents were processed or how many guides made.
5. Only 13 of 26 respondents answered the adoption question.
6. No baseline of any kind.

---

## 9. What this means for our work — and the honest reading

**Cite it for one thing, safely: the TSG quality statistic.** *Missing information 32.24%,
broken links 13.32%, incorrect instructions 11.21%.* That directly supports why our blueprints
have explicit "what to collect" and "stopping condition" fields - the most common complaint
about written procedures is that something is **missing**, not that it is wrong.

**Do not cite it as evidence that automated guide generation works.** By its own numbers it
did not land: satisfaction 2.58/5, utility index 2.74, **NPS -100**, and **0 of 13 engineers**
said they would adopt the guides even with minor edits. The abstract's "61.5% positive
ratings" is the score for **clarity only** - the single best item out of six.

**This is actually useful to us as a negative result.** It says: generating a procedure from
past incidents with an LLM produces something readable that practitioners will not use. Our
approach is the opposite - a blueprint is written from **measurement on our own data**, and
every discriminator must cite the measurement that proved it. This paper is evidence that the
generate-from-history route has a quality problem, which strengthens the case for
measure-first.

**One idea genuinely worth stealing: the literal-extraction rule.** "If the engineer described
an action without showing the command, describe the action and include no command." That is the
same discipline as our **NOT REACHABLE** step marking - say what you cannot do instead of
inventing something plausible. Their phrasing is crisper than ours and the rule is enforceable
by a checker.

**A caution for our own blueprint generator.** `blueprint_to_skill.py` renders skills from
blueprint JSON. FixItFlow's failure mode - fluent, well-structured, and not trusted - is the
one to watch for. Their fix was character-level grounding. Ours is the validator rejecting any
discriminator without a cited measurement. Same idea, and worth saying so.

---

## 10. Safe claims

- Microsoft maintains over 50,000 TSGs used by more than 60,000 practitioners monthly
  (attributed to AutoTSG).
- An internal study found the most common TSG problems are **missing information (32.24%),
  broken links (13.32%), and incorrect instructions (11.21%)** - over half of all complaints.
- FixItFlow generates TSGs from historical incident data with an LLM, using a fixed
  Symptom / Diagnosis / Mitigation structure.
- It enforces character-level grounding: every command must appear verbatim in engineer
  comments, and actions described without commands are written without commands.
- Cleaning removes 35-40% of the data while keeping engineer-written technical content.
- In a survey of 26 engineers, clarity scored 3.46/5 (61.5% positive) but overall satisfaction
  was 2.58/5 and no respondent said they would adopt the guides.

## 11. Do NOT claim

- That FixItFlow was shown to reduce mitigation time by 2.3×. That figure is about incidents
  *having* a guide, not about generated guides.
- That it beats GPT-4o. The paper asserts this but shows no such comparison.
- That automated TSG generation is a solved or validated approach. NPS was -100.
- Any coverage figure. The paper promises one and does not give it.

## 12. Reusable ideas

- **Character-level grounding** for anything an agent will execute. Never paraphrase a command.
- **Say "command not provided"** instead of reconstructing one. The honest gap beats the
  plausible invention.
- **An eligibility filter on input** - at least six engineer comments - so the source has real
  signal in it.
- **A validation checklist run before emitting**, not after.
- **Tag technical content by type** (`kusto`, `shell`, `text`, `json`) so a reader knows what
  they are looking at.
- **Ask the adoption question directly.** "Would you use this?" produced the most informative
  number in the paper, and it was the worst one.
