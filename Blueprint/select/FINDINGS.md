# Blueprint selection — experiment findings (uncommitted research log)

## Experiment 1 — naive aggregate router, Sock Shop (2026-10-28)

Router = `Blueprint/select/README_v1.md`: a light triage (find incident window → rank victims by
wait-rise → read what the top victim waits on → one branch discriminator) that commits to one of
{svc_cpu_cap, noisy_neighbor, slow_db, svc_net, svc_mem_cap, normal} with NO ground truth. Run over
all 42 Sock Shop runs (32 faults across 4 evaluable families + 10 normal controls), gpt-6-luna,
scored by `select_score.py`.

### Result

| true family | correct | notes |
|---|---|---|
| noisy_neighbor | **7/8** | the only family that works — unique aggregate signal (a NEW cpu-hog process appears) |
| svc_cpu_cap | 0/8 | picked "other" ×7 ("host-wide collapse"), normal ×1 |
| slow_db | 2/11 | "normal" ×6, "other"/misc; only 2 committed to db_latency |
| svc_net | 0/5 | "other" ×4, "normal" ×1 |
| **normal (control)** | **10/10** | correctly abstained — zero false alarms |

**Selection on faults: 9/32 = 28%. Specificity on normal: 10/10.**

### Diagnosis (the real finding)

A fault on one request-path service **cascades**: cap/slow/degrade `carts` → every service that
calls it **sleeps waiting** → the whole application's activity drops. So svc_cpu_cap, svc_net and
slow_db all present the SAME aggregate symptom — a synchronized **host-wide activity collapse**.
The light triage sees the collapse and, correctly unwilling to guess, hedges to "other"/"normal".
It only commits when a fault has a signal visible WITHOUT drilling — noisy_neighbor's new process.

The router's conservatism is not the bug — the 10/10 on normal shows it is right to abstain on an
ambiguous symptom. The bug is that the triage **stops at the shared symptom** instead of drilling
to the discriminator. And the drill is hard because of **root-vs-cascade victim identification**:

- The root victim (e.g. `carts`, **runnable**-starved, a few processes) is drowned by the many
  **cascade** victims (callers **sleeping** on sockets waiting for carts).
- Ranking candidate victims by raw wait-rise surfaces the cascade (lots of `S` sleep), i.e. the
  symptom, not the cause. So the agent reads "everyone is waiting for answers" → dependency-ish /
  collapse → hedge.

This matches the matched-arm evidence: given the correct blueprint, the SAME traces score ~87%,
because the specialist drills to the root victim and runs its deciding check. Selection fails
precisely at the step the specialist blueprint does well but the triage skips.

### Fix hypothesis for Experiment 2 (drill-to-root, not patch-to-fit)

1. **A broad collapse is a TRIGGER to drill, never an answer.** Forbid committing to
   "normal"/"other" when a sustained host-wide activity drop is present and unexplained.
2. **Rank candidate victims by root-cause likelihood, not raw wait.** A process that is
   *runnable-starved while CPUs are idle* (cpu_cap) or whose flows show *retransmissions* (net)
   outranks a process merely *sleeping on a socket* (likely a cascade victim). Find the root, then
   read its wait-type.
3. **Walk the cascade to its source.** The sleeping callers all wait on the same peer; follow the
   wakeups / the shared dependency to the one process that is itself starved (CPU or answer) and
   NOT merely waiting — that is the root, and its wait-type picks the blueprint.

Open question: can a *cheap* triage do (2)+(3), or does reliable selection inherently need roughly
the specialist's depth? If the latter, the architecture may become "run the 2-3 candidate
blueprints' cheap first-order checks and compare" rather than a single light router — i.e. the
fingerprint-gated panel (design option B), paid for only on the branch the collapse implicates.

### Numbers that frame it
- Matched arm (correct blueprint given), same Sock Shop traces: ~26-27/31 ≈ 84-87% (preliminary).
- Unassisted selection (this experiment): 9/32 = 28% on faults, 10/10 on normal.
- The gap (≈ 56 pts) is the cost of selection under the naive router — and the target to close.

## Experiment 2 — A (drill-to-root) vs B (fingerprint panel), Sock Shop (2026-10-28)

Same 42 Sock Shop runs, no ground truth, scored by select_score.py. Run from a user-owned tmux
session (my ssh launches kept dropping; the flat run_select_ab.sh works, the nested one hung).

| family | Exp1 naive | A drill-to-root | B panel |
|---|---|---|---|
| noisy_neighbor | 7/8 | **8/8** | 7/8 |
| slow_db | 2/9 | **6/11** | 4/11 |
| svc_net | 0/5 | 1/5 | 1/5 |
| svc_cpu_cap | 0/8 | 0/8 | 0/8 |
| **overall** | **28%** | **47% (15/32)** | **38% (12/32)** |

**A (drill-to-root) wins.** Drilling to the root victim nearly doubled the naive baseline and beat
the panel. B is worse because its precedence hedges when no single check fires cleanly (CPU caps ->
other/normal 7/8), whereas A commits.

**The one unsolved case: svc_cpu_cap = 0/8 in ALL three.** And it fails differently:
- A reads the capped service's slow answers as a slow dependency (cpu -> slow_db, 6/8).
- B can't fire its runnable-starved-while-idle check confidently, so it abstains (cpu -> other/normal, 7/8).

Root cause = a real ambiguity: a CPU-capped service and a service waiting on a slow dependency BOTH
"answer their callers slowly", with callers piling up asleep on sockets. The discriminator neither
nails is WHY the service is slow: starved of CPU (runnable-wait on itself) vs sleeping on its own
downstream call. That single check is the key to closing the gap.

Next lever: add a targeted "is the slow service itself CPU-starved, or waiting downstream?" test to
the drill-to-root router (A). Expected to move cpu_cap off 0/8 and lift slow_db precision.

Framing number: selection 47% unassisted vs ~87% matched-arm; the gap is almost entirely the
cpu-cap<->slow-db confusion plus weak svc_net.

## Experiment 3 — Router C v6 (mechanism-first ladder), Sock Shop (2026-11-01)

Full 42 cells, gpt-6-luna, no ground truth. Router = `Blueprint/select_c/README_v1.md` (v6).

| family | Exp1 naive | Exp2 A | **C v6** |
|---|---|---|---|
| noisy_neighbor | 7/8 | 8/8 | **8/8** |
| svc_cpu_cap | 0/8 | 0/8 | **5/8** |
| svc_net | 0/5 | 1/5 | **4/5** |
| slow_db | 2/11 | 6/11 | **2/11** |
| **faults** | **28%** | **47%** | **59% (19/32)** |
| normal (control) | 10/10 | - | **7/10** |

Overall 26/42 = 62%. Best fault number so far, and **the cpu-cap problem is solved**: 0/8 -> 5/8,
which was the whole point of the v2-v6 iteration. svc_net also recovered (1/5 -> 4/5).

### The new failure, and its cause (measured, not inferred)

slow_db REGRESSED 6/11 -> 2/11, and 6 of the 11 were called `normal`. Cause, from the results:

- **`sock_lag` ran in 0 of 11 slow_db cells. Check 5 never executes.** The agent runs Checks 1-4,
  finds no mechanism, and falls straight through to `normal`. Only 1/11 cells even mentions
  Check 5 - and that one says it "was not run".
- The verdicts say so explicitly: *"the required socket-gap check to distinguish delay-only
  network impairment from a slow dependency"* was skipped; *"no fault mechanism is supported"*.
- Secondary: burst variants get dismissed as transient - *"a brief cross-container dip that
  rebounds"*. Intermittent faults are being read as noise.

This is a blueprint-structure bug, not a model failure. v6 front-loads four negative checks and
places the one POSITIVE test for slow_db last, behind a conditional ("ONLY if 1-4 did not fire").
The agent treats that as optional and stops once nothing has fired. The same over-abstention
shows up inverted on the controls (normal 10/10 -> 7/10): without Check 5 the agent has no
principled stopping point, so it guesses either way.

### v7 — BUILT 2026-11-01, not yet run

v6 archived to `Blueprint/select_c/README_v6_archived.md`; v7 is `README_v1.md`. Four changes,
deliberately narrow - Checks 1-4 are untouched because they are what fixed cpu_cap and svc_net.

1. **Check 5 is now MANDATORY, and `normal` is gated behind it.** "You may not answer `normal`,
   and you may not answer at all, until `sock_lag` has run." Adds the baseline invocation
   (`sock_lag.py $WORK/base.txt 10 all`) so there is something to compare against, says a modest
   rise counts, and gives an explicit fallback when the tool cannot run (say so, then pick from
   the `sched_budget` row) so the agent never silently reports `normal` instead.
2. **A new "bar for answering `normal`" section**: three conditions, all required. Names the
   actual error - "`normal` means I ran the deciding test and gaps match baseline, NOT I did not
   find anything; the second is a report of your own effort, not a finding about the trace."
3. **Intermittent faults.** A short dip is a window to investigate, not noise: slice the DEEPEST
   dip and run every check on that slice; repetition at a cadence is itself evidence.
4. **"Last in the ORDER does not mean least likely."** v6's "slow_db is the *last* option" framing
   read as "disfavoured"; v7 says reaching Check 5 with 1-4 silent is the EXPECTED path for a slow
   dependency, not a sign of health.

**Leakage audit of v7 (clean) - and one defect it found in v6.** v6 told the agent a capped
service sits "near ~0.2 or ~0.5 of a core". Those are quota values from the dataset, so v6's
cpu_cap 5/8 may be partly unearned. v7 removes the numbers ("read the fraction off the tool; do
not expect any particular value"). v7 also drops the words *steady*/*burst*, which echoed the run
filenames, in favour of continuous/intermittent. **Watch cpu_cap when v7 runs: if it drops from
5/8, that is the leak being removed, not a regression in the logic.**

Expected: slow_db 2/11 -> ~8/11 puts faults near 78%; controls should return toward 10/10 since
the agent now has a principled stopping point.

Cost of this arm (`Blueprint/eval/usage_report.py`): 1,953 calls, 32.1M prompt tokens (88%
cached), 581k output, 9.4 min per diagnosis. OpenRouter bills $0 (the key is BYOK - spend lands
on the upstream Azure account); ~$14 estimated at an assumed $1.25/$10 per M, rate unconfirmed.
