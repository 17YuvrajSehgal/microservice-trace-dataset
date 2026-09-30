# Paper Context: AutoTSG — Learning and Synthesis for Incident Troubleshooting (2022)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **This is the real source of the TSG-quality percentages our `table.md` attributes to
> FixItFlow.** FixItFlow restates them as "an internal study" without naming AutoTSG. Correction
> in §7. It is also the best evidence in the pack that **written troubleshooting guides measurably
> help** — which matters, because that is the claim our blueprint idea rests on.

---

## 1. Bibliographic info

- **Title:** AutoTSG: Learning and Synthesis for Incident Troubleshooting
- **Authors:** **Manish Shetty**, Chetan Bansal, Sai Pramod Upadhyayula, Arjun Radhakrishna,
  Anurag Gupta (Microsoft)
- **Year:** 2022 (ESEC/FSE 2022, Industry track)
- **arXiv:** 2205.13457

```bibtex
@inproceedings{shetty2022autotsg,
  title     = {{AutoTSG}: Learning and Synthesis for Incident Troubleshooting},
  author    = {Shetty, Manish and Bansal, Chetan and Upadhyayula, Sai Pramod and Radhakrishna, Arjun and Gupta, Anurag},
  booktitle = {ESEC/FSE 2022 Industry Track}, year = {2022}
}
```

Shetty is also an author on [[aiopslab-2025]].

---

## 2. One-paragraph summary

Microsoft runs **1000+ services** built by **tens of thousands of engineers** across **200+ data
centres**, and on-call engineers lean on **troubleshooting guides (TSGs)**. The authors study
**4,000+ TSGs mapped to thousands of incidents** and show TSGs are **widely used and measurably
reduce mitigation time**. They then analyse **400+ pieces of on-call engineer feedback** and build
**the first taxonomy of TSG quality problems** — which is bleak: **32.24% are about missing
information**. Finally they build **AutoTSG**, which turns prose TSGs into executable workflows by
combining machine learning with program synthesis: **0.89 accuracy identifying actionable TSG
statements**, **0.94 precision / 0.91 recall parsing them for execution**, evaluated on 50 TSGs.

---

## 3. TSGs measurably help — the finding our work depends on

Their dataset is **actual click-throughs** performed by on-call engineers during mitigation, not a
static mapping.

**Usage:** over a period of months, **≈47%, 17% and 8% of TSGs were used at least 2, 5 and 10
times** respectively. **85% of TSGs are linked to high-severity incidents** (1,893), with the
remaining **14% linked to low severity** (840).

**Impact on time-to-mitigate**, restricted to severity 1 and 2 where engineers are paged
immediately, so *"TTM is a reliable proxy for on-call effort"*:

| | Without a TSG | With a TSG |
|---|---|---|
| **Overall (sev 1 + 2)** | **≈19 hrs** | **≈13 hrs** |
| Severity 2 | ≈18 hrs | ≈13 hrs |
| Severity 1 | *see note* | *see note* |

**Note — the paper's severity-1 sentence is self-contradictory.** It reads: *"severity 1 incidents
linked with TSGs (≈36 hrs) had considerably lesser TTM than those without TSGs (≈2 hrs)."* **36 is
not less than 2**; the figures appear transposed. **Quote the overall 19 → 13 hrs and the severity-2
18 → 13 hrs; do not quote the severity-1 numbers.**

**Overall claim, which is sound:** *"TSGs tend to significantly reduce effort during incident
mitigation."*

---

## 4. The TSG quality taxonomy — the numbers we have been mis-citing

From **400+ feedback items** given by on-call engineers. This is their **Table 1**.

| Intent | What it means | Share |
|---|---|---|
| **Completeness** | missing information — examples, links; *"unknown impact and mitigation"*, *"please provide examples"* | **32.24%** |
| **Broken Link** | *"use cases links are broken"*, *"link leads to 404 - not found"* | **13.32%** |
| **Correctness** | incorrect or misleading; *"information is wrong"*, *"steps didn't work"* | **11.21%** |
| **Readability** | *"too much info, not organized"*, *"confusing terminology"* | 10.28% |
| **User Experience** | *"how to execute those code cells?"*, *"badly formatted query"* | 10.05% |
| **Empty** | *"this page is empty"*, *"fill in the TSG, currently just has TODO"* | **7.24%** |
| **Up-to-dateness** | *"out of date: still using visualstudio instead of ado"*, *"deprecated"* | 6.54% |
| **Relevance** | *"doesn't tell me how to renew my cert"*, *"nothing useful here"* | 3.97% |
| Other | unclear or out of scope | 5.14% |

**In an internal Microsoft survey of on-call experience, developers picked TSG Quality & Coverage
as the top pain point.**

**7.24% of TSG complaints are that the guide is empty or still says TODO.** That is worth stating
on its own.

---

## 5. AutoTSG itself

Converts prose TSGs into **executable workflows** by combining **machine learning** (to find which
statements are actionable) with **program synthesis** (to parse them into something runnable).

Evaluated on **50 TSGs**:

| Task | Score |
|---|---|
| Identifying TSG statements | **accuracy 0.89** |
| Parsing them for execution | **precision 0.94, recall 0.91** |

Plus a survey of **ten Microsoft engineers** on the importance of TSG automation and AutoTSG's
usefulness.

---

## 6. What kind of paper this is

- **An empirical study plus a tool**, on real Microsoft TSGs, incidents and engineer feedback.
- The contribution is **converting existing human-written guides into automation**, not generating
  guides and not diagnosing anything.
- **No telemetry, no fault injection, no runtime data.**

---

## 7. A citation to correct in our own files

**`DOCS/reading-papers/table.md` currently attributes these numbers to FixItFlow:**

> **Unnikrishnan et al. 2026, FixItFlow** — *Top TSG complaints: missing information 32.24%,
> broken links 13.32%, incorrect instructions 11.21%*

**They are AutoTSG's, from its Table 1**, derived from 400+ on-call engineer feedback items.
FixItFlow restates them as *"an internal study revealed the most common TSG problems"* **without
naming the source in that sentence** — though it does cite AutoTSG in its reference list ([15]).

**Cite Shetty et al. 2022 for these percentages.** FixItFlow can still be cited for its own
contribution and for its negative result (satisfaction 2.58/5, NPS −100, 0% adoption), which is
genuinely its own.

**This is correction #13**, and like the others it is confined to documentation — no blueprint or
skill uses it.

---

## 8. What this means for our work

**The 19 → 13 hour finding is the evidence that written guides work, and we need it.** Our whole
blueprint idea assumes that a documented, structured diagnostic procedure beats improvising.
**This is the measurement**, from real click-throughs across thousands of Microsoft incidents.
Without it, "blueprints help" is an assumption.

**The quality taxonomy is a specification for what a blueprint must not be.** Reading it as a list
of failure modes to design against:

| Their complaint | What it means for a blueprint |
|---|---|
| **Completeness 32.24%** — "unknown impact and mitigation" | every blueprint needs a **rule-out list** and a stated conclusion, not just a signal |
| **Correctness 11.21%** — "steps didn't work" | **evidence-first**: nothing enters a blueprint until measured on our data |
| **Up-to-dateness 6.54%** — "deprecated" | record the **kernel version and applicability**; our `applies_to` field exists for this |
| **Empty 7.24%** — "currently just has TODO" | a blueprint with an empty `evidence_from_literature` is this category |
| **Readability 10.28%** — "too much info, not organized" | the plain-language rule |

**That last row is worth sitting with.** Three of our blueprints have an empty
`evidence_from_literature` field — we found that while fixing the citation problems. By AutoTSG's
taxonomy that is the **Empty** category, 7.24% of all complaints.

**AutoTSG's actual technique is the opposite of ours, and the contrast is the interesting part.**

| | AutoTSG | Our blueprints |
|---|---|---|
| Starting point | **existing prose TSGs** written by engineers | **measurements on our own data** |
| Method | ML + program synthesis to make prose executable | write the procedure executable from the start |
| Risk it inherits | **everything in the Table 1 taxonomy** — you automate whatever the guide says, including the wrong steps | the risk is that our measurement is wrong |

**So AutoTSG's ceiling is the quality of the input guide, and its own study says 11.21% of guides
have incorrect steps.** Automating a wrong procedure faithfully is still wrong. **That is a good
argument for measure-first**, and it is stronger coming from their own data than from us.

**Three papers now say the same thing from different directions**, and this is the related-work
argument for our approach:

| Paper | Approach to TSGs | Outcome |
|---|---|---|
| **AutoTSG 2022** | **automate** existing guides | works (0.89/0.94/0.91), but inherits their quality problems |
| **Nissist 2024** | **restructure** guides into intent/action/linker nodes | 60% shorter TTM where a TSG existed |
| **FixItFlow 2026** | **generate** guides from incident history | satisfaction 2.58/5, **NPS −100, 0% adoption** |

**None of them creates the knowledge; they all move existing knowledge around.** Our position is
that the knowledge has to be **measured first** — which is a different claim from all three, and
now clearly so.

**One scope note.** AutoTSG is about **Microsoft's internal TSGs for arbitrary service incidents**,
not about performance faults or telemetry. Cite it for **TSG value and TSG quality**, never for
anything about diagnosis from data.

---

## 9. Safe claims

- Microsoft operates **1000+ internal and external services**, built by **tens of thousands of
  engineers**, deployed in **200+ data centres**.
- Study of **4,000+ TSGs mapped to thousands of incidents**, using **actual on-call
  click-throughs**, not a static mapping.
- **≈47%, 17% and 8% of TSGs were used at least 2, 5 and 10 times** over a period of months.
  **85% are linked to high-severity incidents** (1,893); 14% to low severity (840).
- **Mean TTM for severity 1-2 incidents: ≈19 hrs without a TSG, ≈13 hrs with one.** For severity 2
  specifically, **≈18 hrs → ≈13 hrs**. *"TSGs tend to significantly reduce effort during incident
  mitigation."*
- **In an internal survey, developers picked TSG Quality & Coverage as the top on-call pain
  point.**
- Taxonomy from **400+ on-call engineer feedback items**: **Completeness 32.24%, Broken Link
  13.32%, Correctness 11.21%, Readability 10.28%, User Experience 10.05%, Empty 7.24%,
  Up-to-dateness 6.54%, Relevance 3.97%, Other 5.14%.**
- AutoTSG converts TSGs to executable workflows using **ML plus program synthesis**: on **50
  TSGs**, **accuracy 0.89** identifying statements, **precision 0.94 / recall 0.91** parsing them.
- Surveyed **ten Microsoft engineers** on the importance of TSG automation.

## 10. Do NOT claim

- **The severity-1 TTM figures (≈36 hrs with TSG vs ≈2 hrs without).** The paper's own sentence
  says the 36 is *lower*, which is impossible; the values appear transposed. Use the overall and
  severity-2 numbers.
- That FixItFlow produced the 32.24% / 13.32% / 11.21% figures. **They are AutoTSG's Table 1.**
- That AutoTSG generates or validates guides. It **automates existing ones**, and inherits their
  errors.
- That the parsing scores reflect end-to-end incident resolution. They measure **statement
  identification and parsing on 50 TSGs**.

## 11. Reusable ideas

- **Measure whether documentation helps before building tooling for it.** 19 → 13 hours is what
  makes the rest of the paper worth doing.
- **Use click-throughs, not links.** A TSG "mapped" to an incident means nothing; a TSG *opened
  during* mitigation means it was used.
- **Taxonomise the complaints.** Their Table 1 is a design specification for any diagnostic
  document, ours included.
- **Restrict the impact analysis to cases where the proxy is valid.** They used only severity 1-2
  because those page immediately, so TTM reflects effort rather than queueing.
- **Automation inherits the source's errors.** 11.21% of guides have steps that do not work, and
  synthesis will reproduce them faithfully.
