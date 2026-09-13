# 13 Sept 2026 — blueprint design, points 1-3

Yuvraj raised four design points. Three are done; the fourth is measured but not fixed.

---

## 1. One source of truth for every threshold

**The numbers lived twice** - as prose in each `blueprint.json`, and as Python literals in
`blueprint_decide.py`. Nothing compared them.

They had drifted, and two blueprints were documenting rules we had **already measured and
rejected**:

| Blueprint | Said | Engine actually used |
|---|---|---|
| `host-disk-saturation` | "at least 2000 disk requests per second" | a ratio, 450 req/s per unit of interrupt rise |
| `service-memory-cap` | "interrupt time at least 2.5x" AND "no process gains 500+ req/s" | IRQ_X 2.0 with the ratio |

The disk figure was read off Sock Shop v1 and **scored 1/10 on v2**. The memcap pair is
recorded in the engine's own comment as having **scored 3/16** before replacement. So anyone
following either blueprint was following a broken rule, and only the code was ever tested.

**Decision: `blueprints/thresholds.json` is the only place a number lives.** The engine
imports it - no bare numeric constant is left in `blueprint_decide.py`. Blueprints quote
`{NAME}` and the skill generator substitutes the live value, so the agent still gets a real
number while the document keeps the name.

**One thing worth remembering.** My first drift check matched on units - `N requests per
second` - and it **missed the actual historical bug**, because the prose read "2000 **disk**
requests per second" and one word in the wrong place blinded it. Matching units is guesswork.
The check now rejects any bare digit in `verdict_when`. Verified by putting the original
wording back and watching it fail.

---

## 2. Thresholds with units measure our hardware, not the fault

Yuvraj's point: if the disk were faster the symptom would differ or vanish, but the problem
would still be there. He is right, and we already had the worked example - the 2000 req/s
figure above.

Audited all 16 constants: **9 travel, 6 do not, 1 partly.** Anything that is a ratio to the
run's own baseline, a share of capacity, or a presence test, travels. Anything with units does
not.

Tested all six unit-bearing ones over 272 runs on a **12-core** host and a **16-core** host,
so converting cores to a share is a real test rather than a rename.

**Adopted** - measured as good or better:
- `BIG_THIEF` 4.0 cores -> **0.297 share of host cores**
- `FORK_NEWCOMER` 26.34 forks/s -> **0.176x the host's own baseline fork rate**
- `EMFILE` 0.13-9.28/s -> **a share of all failing syscalls**. The obvious normaliser, a ratio
  to baseline, is *undefined* here because EMFILE is exactly zero in almost every baseline.

**Not adopted** - and this is the more interesting half:
- `THIEF_CORES`: in cores the band admits **zero** negatives; in share units it admits
  **eight**. Absolute wins because **the fault itself is absolute** - a co-tenant is a
  container configured with N workers, not with a fraction of the machine.
- `TX_NEWCOMER`: share of window egress scores the same 10/10 but the margin **collapses from
  22.3x to 1.15x**. We call 1.01x dangerous elsewhere.

**Neither:** `LOSER_CORES` has 219 negatives inside its band in cores and 220 in share. It
does almost no discriminating work in either form. Recorded rather than quietly tuned.

**A mistake worth keeping.** I first set `BIG_THIEF_SHARE` to 0.167, the value separating host
saturation from everything below. But that is the **floor of saturation**, and it lands exactly
on the **top of the co-tenant range** - so as a strict upper bound it excluded the largest
co-tenant run and cost one of sixteen. **A separation cut and a ceiling are not the same
number.** Re-derived with headroom both ways: 0.297, 1.78x clear each side.

End-to-end before and after: **85/116 both**. The change costs nothing and drops a dependency
on core count.

---

## 3. Processing steps must run where the incident is

54 steps; only **11** declared a capability. The other 43 were raw commands needing `<app>`,
`<run_id>` and `<family>`.

**`<family>` is the ground-truth fault name.** A blueprint that needs the fault family before
it can run the analysis is not doing RCA, and in the harness it hands the label to the model
under test. They also hardcoded `/scratch/yuvraj17/...`.

This was a **regression against a rule the README already stated** and the validator already
supported. The processing block had grown past it.

All 54 steps now declare a capability. 17 registered, 4 new. Every binding resolves through
`$BLUEPRINT_HOME`. Only `<trace_dir>`, `<window>` and `<out>` survive as inputs.

---

## 4. Anti-pattern vs actual problem — measured, not fixed

**46 false fires out of 156 runs where no blueprint should fire (29%).**

| Fault actually present | What the engine said |
|---|---|
| `code_serial_awaits`, `code_event_loop_block`, `code_unbounded_cache`, `code_lock_across_io`, `code_n_plus_one` | **datastore-wait** (14 runs) |
| `anomaly_mem` | service-memory-cap x15 |
| `nagle_delayed_ack` | host-disk-saturation x10 |
| `conn_pool_exhaustion` | datastore-wait x3 |

Every anti-pattern family collapses into one blueprint. A service doing serial awaits **is**
waiting; the rule sees waiting and blames the datastore. The datastore is fine.

Two things that clear up the picture:
- **Healthy runs never false-fire** - `normal` is 0 of 20. The engine is not trigger-happy in
  general; adjacent faults trip it.
- **Cascades are not the problem.** Only 5 of 272 runs have two blueprints firing. I expected
  this to be the issue and it is not. Under-discrimination is.

`nagle_delayed_ack -> host-disk-saturation` 10 of 10 looks like a plain bug, not a subtle
confusion. Separate investigation.

**Untested idea for the fix:** an anti-pattern is present in the **baseline** window too; a
fault appears only in the incident window. We already collect both, so the test costs nothing
new. Not measured yet - flagged as a hypothesis.

---

## Still open

- Point 4 above: build and measure the baseline-presence test.
- `nagle_delayed_ack -> host-disk-saturation`, 10/10 wrong.
- `service-memory-cap` vs `anomaly_mem` remain inseparable (15 of 16 false fires).
- G2 early detection, which also unlocks the timeline Naser asked for first.
- The with/without agent comparison on v2 is still not run.

---

# Point 4 — anti-pattern vs actual problem (done)

**46 false fires -> 19. Recall unchanged at 85/116.** Three separate causes, one of them bad.

## The hypothesis was wrong, and untestable here

"An anti-pattern is in the baseline window too; a fault is not." `code_defect_lib.sh` restarts
the container with `STRATA_BUG` set **at the incident boundary**, so in our runs a defect is
absent from baseline exactly like a fault. Recorded rather than dropped - it may still be right
on production data.

## What worked was backwards from what I expected

I assumed anti-patterns would look WEAKER than a real fault. They look much stronger.

| | socket wait, x baseline |
|---|---|
| `slow_db`, 22 runs | 1.07 - 144 |
| five code-defect families, 25 runs | **651 - 2462** |

A ceiling at 306 (geometric midpoint) keeps 22/22 owned and excludes 25/25 defects, 2.13x clear
both ways.

**The mechanism is the point.** A slow dependency still ANSWERS - the caller keeps working, just
slower. Broken code in the caller stops the work, so its poll call sits parked for most of the
window. **Waiting a thousand times longer than normal is not a slower callee, it is a caller
that stopped.**

## A gate that passed when it could not run

`answers_slowly = (not endpoint_available or ...)`. A run with no endpoint timing PASSED the
check that something is answering slowly. Three false diagnoses came in that way. Now fails
closed. Endpoint timing is missing in 14 of 20 healthy runs, so this was not a corner case.

## The worst one: we were diagnosing our own instrument

`nagle_delayed_ack` fired `host-disk-saturation` **10 of 10**. The process "arriving on the
disk" in every one was **`lttng-consumerd`** - our trace collector - gaining ~1000 req/s
against 37-66 in a healthy run.

The tracer was missing from the INFRA list, and the disk rule never consulted that list anyway.
Excluding it removed all 10, cost no recall (the real disk fault names the injected load
generator in all 10 of its runs).

**Observer effect: for one fault family we were measuring the measurement.** It hid because the
rule produced a confident, well-formed, completely wrong answer. Logged as CAMPAIGN-ISSUES 16.

## Stopping conditions, which is what was actually asked

`stop_and_switch` used to just name another blueprint. It now says **switching away does not end
the investigation** - each alternative names a different cause for the same symptom, so the
measurement carries across rather than being thrown away.

## Method note worth keeping

My first attempt invented a new signal - per-call latency against call count - and found total
overlap. The reason: "the slowest endpoint" is a DIFFERENT endpoint in every run, so it never
compared like with like. Looking at what the rule actually measured on the runs it got wrong
took ten minutes and pointed straight at the answer. **Diagnose the rule before inventing a
signal.**

## What is left

19 false fires, both already-known: `anomaly_mem -> service-memory-cap` x15 and
`fd_exhaustion -> service-memory-cap` x4. Both need the memory-cap rule re-derived against
`anomaly_mem`, which is still open from 8 Sept.
