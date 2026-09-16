# What to read, and in what order

Written 15 September 2026. This repo has about 120 markdown files and they are not all current.
This says which ones to read, what each is, and which to skip.

Each entry was checked by opening the file, not guessed from its name.

---

## Start here — five docs

Read these in order. They are enough to understand what this project is and what state it is in.

| # | doc | what it is |
|---|---|---|
| 1 | `CLAUDE.md` | The map. Current state, hard-won technical facts, where everything lives. Short |
| 2 | `blueprints/README.md` | What a blueprint **is** — one solved investigation written down so a person or an agent can re-execute it. The core idea of the current work |
| 3 | `blueprints/docs/DATASET-v2-INVENTORY.md` | What the dataset actually contains: 303 runs, sizes, per-family counts, and the caveats that affect analysis |
| 4 | `research-agentic-rca.md` | The current research framing — agentic RCA under telemetry degradation |
| 5 | `CAMPAIGN-ISSUES.md` | Live list of what is wrong with the data and whether it needs re-collecting or only re-scoring. **Read before trusting any run** |

---

## Two things that will confuse you

**`msr-research.md` vs `research-agentic-rca.md`.** `CLAUDE.md` calls `msr-research.md` "the
research plan", but `research-agentic-rca.md` opens by saying it *supersedes the framing in
`msr-research.md`*. Both are still here. Treat `research-agentic-rca.md` as current;
`msr-research.md` is the earlier modality-ablation framing, which the MSR paper still targets.

**Three files are byte-identical duplicates.** Verified by checksum:

- `DATASET_GUIDE.md` == `stratatrace-v1/DATASET_GUIDE.md`
- `fault_catalog.md` == `stratatrace-v1/fault_catalog.md`
- `release/FREEZE-v1.md` == `stratatrace-v1/provenance/FREEZE-v1.md`

Read the root copy. The `stratatrace-v1/` copies exist because v1 was packaged as a release.

---

## The dataset

| doc | what it is |
|---|---|
| `understanding-dataset.md` | Guide for someone opening the data for the first time, walked through one fault family |
| `DATASET_GUIDE.md` | Longer from-scratch guide: what was collected, how, why, what it looks like, how many runs |
| `fault_catalog.md` | **Pre-registered** predictions — which modality should see which fault. Cannot be edited in place; changes go through its §7 amendment log |
| `blueprints/docs/AUDIT-v2-full.md` | Every run checked. 59 of 303 not okay, split into "the injection did not take" and "the baseline is contaminated" |
| `blueprints/docs/RECOLLECT-list.md` | What needs re-collecting — and, just as useful, the runs that look broken but are not |
| `blueprints/docs/FAULT-CATEGORIES-V2.md` | How the fault set went from 5 issue types to about 10 |
| `blueprints/docs/CODE-BUGS-V2.md` | Injecting real code defects, not just infrastructure faults |

---

## The blueprints track — the primary work

| doc | what it is |
|---|---|
| `blueprints/docs/blueprint-report.md` | Plain-English account of every design decision. The one to read before presenting the work |
| `blueprints/docs/FINDINGS-phase1.md` | The big one, 64 KB. Running log of what the kernel-trace specificity work actually shows. Newest first |
| `blueprints/docs/BLUEPRINT-BACKLOG.md` | Which anomalies to write next, ordered by measurement rather than by counting coverage |
| `blueprints/docs/LATENCY-CAUSES.md` | Why a request gets slow, and which of those causes kernel traces can actually see |
| `blueprints/docs/COVERAGE-which-blueprints-are-missing.md` | Where we hold data but have no blueprint for it |
| `blueprints/docs/RESEARCH-PLAN-phase1-kernel.md` | The protocol `blueprints/docs/FINDINGS-phase1.md` is logging against |

---

## Results

| doc | what it is |
|---|---|
| `blueprints/docs/RESULTS-withwithout.md` | With vs without a blueprint — 57 incidents, both apps, same model, same evidence |
| `blueprints/docs/RESULTS-comparison.md` | Blueprint vs the alternatives — 12 incidents, same data, same scorer |
| `blueprints/docs/RESULTSv2.md` | All 5 blueprints, 81 test runs, two apps, kernel traces only |
| `blueprints/docs/RESULTS-antipattern-ceiling.md` | Telling an anti-pattern apart from an actual problem |
| `blueprints/docs/RESULTS-verification-filter.md` | What filtering on `verification_status` does to recall and false fires |
| `blueprints/docs/RESULTS-blueprint-cards.md` | The per-blueprint evidence cards and how to read them |

---

## Writing targets

| doc | what it is |
|---|---|
| `thesis/PROPOSAL.md` | M.Sc. thesis proposal — agentic software observability |
| `thesis/ABSTRACT.md` | The short version |
| `paper/fse-draft.md` | FSE 2027 draft: how much observability does an LLM agent need? |
| `blueprints/docs/COLLECTION-V2-SPEC.md` | The one-shot collection spec. Its rule: *we do not get a second run* |
| `non-llm-baseline.md` | The non-LLM baseline we compare against (RCAEval + multi-source BARO) |

---

## Reference, when you need it

| doc | what it is |
|---|---|
| `CLUSTER-LAYOUT.md` | Where everything lives on Trillium. Read before running cluster jobs |
| `transfer/README.md` | How data moves between the collection VM and Trillium |
| `microservice-lttng-data-collection-scripts/TROUBLESHOOTING.md` | Collection gotchas and their fixes |
| `microservice-lttng-data-collection-scripts/faults/README.md` | How the fault recipes work, including the Docker API traps |
| `future.md` | Parked work, with enough detail to pick it up later. Each entry says why it waits |
| `progress-notes/next-steps.md` | Where things stand right now, then read the latest `progress-notes/` day |
| `blueprint-idea.md` | Where the blueprint idea came from (2026-08-26 meeting) |

---

## Skip these

| what | why |
|---|---|
| `stratatrace-v1/DATASET_GUIDE.md`, `stratatrace-v1/fault_catalog.md`, `stratatrace-v1/provenance/FREEZE-v1.md` | Byte-identical to the root copies |
| `DOCS/` | JSS-era. `CLAUDE.md` records that its paths point at the old `adaptive_tracer` workspace |
| `README.md` | Describes the v1 Sock Shop dataset. Predates the four-modality work |
| `archive/` | The LMAT/JSS modeling stack, archived 2026-08-08. Nothing current imports it |
| `todolist.md`, `update-09-09-2026.md`, `new_design.md` | Point-in-time snapshots. `progress-notes/` is the live log |
| `archive/progress-snapshots/` | Superseded dated progress files, same reason |

---

## A note on `progress-notes/`

This is the live decision log, one folder per day, day-first dates. It records **why** things were
decided, not what was done. When something in the code looks arbitrary, the reason is usually
there. Read the latest day first; the rest is history you can search when you need it.
