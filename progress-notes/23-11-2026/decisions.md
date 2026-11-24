# Decisions, 23-11-2026

## 1. All 25 blueprints are in the new form

Converted the last eight: 1 (document fields added to the prototype file), 3, 5, 7, and
the bare-metal ones 0, 8, 9, 10. All 25 pass `bp_check.py`, and each has a `BLUEPRINT.md`
generated from its `blueprint.yaml`. Open items are in `Blueprint/latency/TO-FIX.md`
(C23 to C30 are new).

Decisions:

- **Tools were not changed.** In 1, 3, 5, 7 the decisive tools print tables, not a verdict
  line. A verdict line needs bars, and bars need sweeps. So those steps rest on the agent
  reading a table, and each file's status says so. Stays in TO-FIX (C11).
- **Triage is its own kind.** Blueprint 0 confirms nothing; it sends the case to 8, 9, 10
  or 11 through hand-offs. `fault_type: triage`; the checker does not ask it for a
  confirming outcome.
- **Where README and tool disagree, the yaml follows the tool**, as before. The bare-metal
  READMEs had the same drift as 11 (a verdict that is no longer printed, verdicts that are
  printed but not listed).
- **Blueprint 5 covers `svc_net` and `anomaly_net`**: one-path loss against host-wide loss.
  The README does not use the family names; the mapping comes from its run counts.
- **Blueprint 5 "no loss shown" is inconclusive**, not rejected: added delay leaves no
  drops, the README says so.
- **Partner rule kept**: the bare-metal files were built only from READMEs and tools already
  in git, with the READMEs' neutral wording.

State of evidence, which the status line of each file now states:

| blueprints | labelled sweep | agent run in the new form |
|---|---|---|
| 12 to 24, 2, 4, 6, 11 | yes | one run per family (20-11) |
| 1 | no (older evaluation only) | one run, confirmed |
| 3, 5 | 3: no. 5: counts in the README, no results file | not run |
| 7 | none, never calibrated | cannot be run (no labelled family) |
| 0, 8, 9, 10 | partner traces, not public | not run; local model only |

Not done today: any agent run. The Trillium connection was closed, so 3 and 5 are
untested, and the tools of 3, 5, 7 are not copied to the cluster yet.
