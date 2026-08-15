# v4 feature test — does the skill/context stack work as intended? (2026-08-15)

20 leakage-audited runs (11 new + 9 prior smokes/partials) across S1 (skills-full), LOFO,
brief-injection, and query_source, compared per-incident against the S0 = gate-v3 baseline.
Auditor: PASS on every transcript. Verdict: **the machinery works as designed — the accuracy
lever is selector calibration, plus one genuine tool gap (topology can't see span-less
datastores).**

## What works as intended

- **Skill-guided wins**: TT `svc_cpu_cap` flipped S0 both=✗ → S1 **both=✓** (right skill chose
  cpu_throttling — the taxonomy fix skills were meant to deliver). Clean matches run cheaper
  (9–12 calls vs 12–16 in v3) and host-fault families stay fully correct.
- **Abstain + fallback**: SS `anomaly_disk` LOFO — correct abstain among 11 distractors,
  fallback fully correct (the never-seen-fault path).
- **Skill override**: TT `dependency_outage` LOFO — the selector picked a WRONG skill
  (db-latency), and the agent **abandoned it and still got both=✓**. The "abandon if evidence
  contradicts" instruction can work.
- **Brief injection**: no harm anywhere; one improvement (SS `svc_mem_cap` service ✗→✓); the
  correct case (SS `anomaly_mem`) stayed correct.
- **query_source**: used organically in 2/20 runs (didn't flip outcomes); infra works.

## What doesn't (ranked by impact)

1. **Selector calibration — S1 precision 6/11, LOFO abstention 1/4.** Three failure shapes:
   (a) *adjacent-class confusion*: noisy_neighbor→host-cpu-pressure, slow_db→service-network,
   svc_mem_cap→frozen-dependency, dep_outage→db-latency under LOFO. The look-alike
   discriminators exist — but they live in the Resolution template, which the selector never
   sees (it only reads Problem signatures).
   (b) *wrong abstains on absence-shaped faults*: TT anomaly_net and SS queue_backlog have
   skills whose signatures describe absences ("nothing saturated", "KPIs near-normal") — hard
   to match confidently.
   (c) LOFO distractors attract path-shaped/adjacent evidence instead of triggering abstain.
2. **Topology is blind to span-less components — the real cause of the slow_db misses.**
   Edges come from span parent→child links, so a datastore that emits no spans (mysql, *-db)
   NEVER appears as a callee. "Slow edges converge on the datastore" — the db-latency skill's
   signature and the agent's convergence reasoning — is structurally unobservable on TT; the
   evidence genuinely looks like service-network-path. Spans carry `network.peer.address` /
   `server.address`: client-span→peer edges would make datastores visible callees. Generic
   fix, not fault-specific.
3. **SS queue_backlog regressed to "normal" under S1** (v3 at least named a service). The
   silent-fault signature needs positive evidence the tools barely surface (consumer
   span-rate drop, broker asymmetry).
4. **Brief doesn't save calls yet** (12–27 calls with brief) — the agent re-surveys anyway
   because nothing tells it the survey is already done.

## Improvement plan (proposed, in order)

| # | Change | Type | Attacks |
|---|---|---|---|
| A | Topology: add client-span→peer edges (from `server.address`/`network.peer.address`) so span-less datastores appear as callees | tool, generic | slow_db misses, db vs service_network confusion |
| B | Selector v2: selector also sees each skill's discriminating boundary lines; instructed to compare top-2 candidates and check discriminators before committing; explicit pass over absence-shaped skills before abstaining | selector | 1a, 1b, 1c |
| C | Skill preamble: "FIRST verify this skill's signature via its discriminating checks; if any fails, state that and revert to the general method" — make the TT dep-outage override the norm | prompt | wrong-skill steering |
| D | Brief preamble: "the survey above already covers the no-filter overview — go straight to targeted queries" | prompt | call savings |
| E | Skills reference query_source where code confirmation helps (error-burst, memory-cap) | skills | unused synergy |
| F | queue_backlog: investigate surfacing consumer span-rate drop / broker asymmetry in traces or metrics | tool, later | known-hard silent fault |

Then ONE re-test of the same 11-incident set (plus slow_db/anomaly_net S1) before any bigger run.

## Raw table

See `results/v4_test/` + `v4_report.py` on Trillium. Selection: S1 6/11, LOFO abstain 1/4;
query_source 2/20; auditor PASS 20/20.
