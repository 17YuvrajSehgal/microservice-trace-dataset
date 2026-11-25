# Final plan: papers, thesis and product

Written 25-11-2026. This is a planning document, not a result. Deadlines and journal facts in
it are **not verified**; check every call for papers and every journal site before relying on
a date or a ranking.

## 1. What we have that is publishable

| Contribution | What is new | How strong today |
|---|---|---|
| The dataset: four modalities (metrics, logs, spans, kernel traces), two applications, labelled faults | few public datasets have kernel traces next to the other three signals, with ground truth | strong: 304 v2 runs, plus the v3 families now being collected |
| The blueprints: a written procedure plus small tools that find one fault in a kernel trace | each one is proven on data, with a false-alarm check on every other run | strong at tool level; weak at agent level |
| The modality study: which signal sees which fault | predictions were written down before collection (`fault_catalog.md`), and some were wrong | good, and unusual |
| Collection lessons: six verification targets were wrong, baselines were contaminated, faults with no metric signature | "the fault was real and the check was wrong" is a result, not housekeeping | good supporting material |
| The industry case: bare-metal line cards, three solved cases | real engineers, real incidents | strong, but limited by the NDA |

## 2. The papers

| | Paper | Claim | State |
|---|---|---|---|
| A | Dataset paper | a verified four-modality dataset with kernel traces, and what verification taught us | data and lessons exist; mostly writing |
| B | Method paper (the main one) | a written, tested procedure makes an LLM agent find the root cause where a free-running agent does not | tools done for about 30 families; agent evaluation and baselines missing |
| C | Modality study | which of the four signals is needed for which fault, against pre-registered predictions | data exists; can be a section of B or its own paper |
| D | Industry paper | the method on bare-metal line cards, with the partner | needs the partner's approval of every sentence |

## 3. The gap: what reviewers will ask

| Question | Today |
|---|---|
| Does the agent work, not only the tools? | open: almost no agent runs on blueprints 4 to 28 |
| How does it compare with existing root-cause methods? | open: no baseline has been run on this data |
| Are the faults realistic, or tuned to be found? | partly: many faults are a helper container, and some bars are fitted |
| Does it generalise beyond two demo applications? | partly: the line-card cases help here |
| How many false alarms? | good for most blueprints; three have documented ones; blueprints 25 to 28 are not yet checked against other families |

The first two rows decide whether Paper B is a research paper or a tools paper. No venue
changes that.

## 4. Where to submit

### Journals

| Journal | Standing | Best fit |
|---|---|---|
| IEEE Transactions on Software Engineering (TSE) | top software engineering journal | Paper B |
| ACM Transactions on Software Engineering and Methodology (TOSEM) | equal top with TSE; allows long papers | Paper B with all families |
| Empirical Software Engineering (EMSE) | top journal for empirical studies | Paper A, or Paper C |
| IEEE Transactions on Parallel and Distributed Systems (TPDS) | top systems journal; published the wait-analysis paper our tools build on (Giraldeau and Dagenais, 2016) | a kernel-tracing version of Paper B |
| IEEE Transactions on Services Computing (TSC) | strong for services and cloud | Paper B or C |
| IEEE Transactions on Network and Service Management (TNSM) | strong for network operations | Paper D |
| IEEE Transactions on Dependable and Secure Computing (TDSC) | top dependability journal | a failure-diagnosis framing of B |
| Journal of Systems and Software (JSS) | solid, a tier below TSE and TOSEM | a safe choice |
| Scientific Data | high-visibility data journal | the dataset alone |

TSE, TOSEM and EMSE papers can be presented at ICSE, FSE or ASE through their journal-first
tracks. Journals are slower than conferences but allow revision, and they have room for all
the material.

### Conferences

| Venue | Fits | Note |
|---|---|---|
| ICSE or FSE research track | Paper B | highest bar; needs the agent evaluation and baselines |
| ASE research track | Paper B | similar bar; often friendlier to tool-heavy work |
| ICSE SEIP, FSE Industry, ASE Industry | Paper D | shorter; real use matters more than baselines |
| ICPE | Paper B or C | performance-engineering audience |
| MSR Data Showcase | Paper A | the project notes name MSR 2027 with a paper deadline of 10 November 2026, which has passed; whether anything was submitted is not recorded here |

### Recommendation

- Paper B to **TSE or TOSEM** (TOSEM if it gets long). TPDS as the alternative if we prefer
  the systems and tracing community.
- Paper A to **EMSE**: its strength is the verification story and the pre-registered predictions.
- Paper D to an **industry track**, once the partner agrees on what can be said.

## 5. The thesis

One thesis covers all of it. Chapter order:

1. Background: tracing, observability signals, root-cause analysis, LLM agents.
2. The dataset and how it was verified (Paper A).
3. The blueprint method and the tools (Paper B, first half).
4. Evaluation: tools, agent, modalities, false alarms (Paper B second half, and C).
5. The industrial case, as far as the NDA allows (Paper D).
6. Limits and future work.

If the program allows a thesis by articles, Papers A and B can be chapters almost as written.
This must be checked with the supervisor.

## 6. The product for the partner

- **It needs:** an on-site model (no data leaves their network), the bare-metal blueprints, a
  clear way to add a new blueprint, a user guide, and an agreed acceptance test on their traces.
- **It does not need:** the microservice families, baselines, or the modality study.
- **The overlap with the papers:** the blueprint format, the agent, and the tools. Every
  blueprint we validate serves both.
- **Risk:** the papers want the partner's cases described, and the NDA limits that. Agree in
  writing, early, on what may be published. Partner names stay out of git and out of the
  product repository.

## 7. Order of work

1. **Freeze the scope of Paper B:** about 30 families, both applications, tool results, agent
   results, one baseline.
2. **Run the false-alarm check for blueprints 25 to 28** (one SLURM job; deferred so far).
3. **Run the agent evaluation.** This decides the level of Paper B. It is the only step that
   costs API credits or GPU time, so it needs a budget first.
4. **Run one baseline** from the existing root-cause literature on the same runs.
5. **Write Paper A in parallel.** Its data and lessons already exist.
6. **With the partner:** fix a delivery date and an acceptance test, and ask what may be published.
7. **Keep collecting v3 families** one at a time; each new family adds a blueprint to Paper B
   until the scope is frozen.

## 8. Open questions (they change the plan)

- When must the thesis be submitted, and is an accepted paper expected before that?
- What exactly was promised to the partner, and by when?
- Was anything submitted to MSR 2027?
- How much can be spent on the agent evaluation, in API credits or GPU hours?
- Which baseline method do we compare against?
