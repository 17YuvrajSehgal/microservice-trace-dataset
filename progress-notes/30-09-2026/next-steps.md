# Next steps, as of 30 September 2026

Full detail and the "how" for each: `meeting-notes/ACTIONS-30-09-2026.md`.

## Do next, in order

1. **Pick one category and one problem.** Recommend latency - Naser says you know it, and we have
   the most measured evidence for it. Write one page in your own words, without AI.
2. **Understand that problem.** Reproduce it, open a real trace in Trace Compass, have it
   explained. Done when you can explain its kernel signature without notes. This is the task the
   feedback was actually about.
3. **Ten papers on that one category.** Keep only the relevant ones from the ~100 collected. For
   each: problem, detection technique, GitHub repo yes/no.
4. **The repos.** Mahsa would do this before the prose. Read how each detects the symptom.
5. **Rewrite that one blueprint** with references, symptom provenance, and a design rationale.
6. **Build the blueprint-only arm** and evaluate all three. Report accuracy AND time.
7. **Write the report** on that one problem.
8. **Catalog structure** (`blueprint-catalog/category-N/<problem>/`) and zip example traces in.

## Parked deliberately

- The 11-problem campaign. Breadth; the feedback asked for depth.
- Attaching the ~100 references. This is the specific thing that was rejected.
- Anti-pattern papers. Naser: "That's not the focus now."
- The full category taxonomy. Placeholder names until problems are finished.

## Small, unblocked

- Fix the trailing comma in `deadlock-lock-order/blueprint.json`, and make the validator fail on
  unparseable JSON instead of skipping it.
- Find the modern replacement for `sched_ttwu`, verify it on a real trace, cite Naser's paper.
- Read the thesis Naser shared. Asked twice; it is the basis for the catalog structure.

## Harness state - done, not in progress

This week's fixes are committed, pushed, and smoke-tested except where noted:

- worker wrap-up turn (was losing 98 of 554 workers' findings entirely)
- `ctf_lines` reports a truncated scan and where to look instead
- per-cell driver timeout (a cell hung 43 minutes with no clock on it)
- `MAX_WORKER_STEPS` 12 -> 18, `THREAD_BUDGET` 80k -> 150k, `ctf_lines` cap 25k -> 42k
- the hang fixes have NOT run live yet. Re-smoke before any real matrix.
