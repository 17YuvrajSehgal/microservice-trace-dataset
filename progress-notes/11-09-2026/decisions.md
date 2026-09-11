# 11 September 2026 — decisions

## Context

Trillium came back. All 272 packs now carry the new process signals, so the 16 uncovered faults
could finally be measured against every other family at once.

---

## 1. Right-sized every walltime, from measurements

I had been asking for 6-8 hours for jobs that finish in under one:

| job | actual | asked |
|---|---|---|
| 156 packs | 0:57:48 | 6:00:00 |
| 136 packs + decide + score | 1:00:14 | 8:00:00 |
| 62 runs, one measurement | 0:20:37 | 6:00:00 |
| extract 303 bundles | 0:18:39 | 4:00:00 |
| decompress the tree | 0:16:05 | 6:00:00 |

Between 6x and 22x over. A long request waits far longer in the queue than a short one, so
over-asking costs wall-clock time even on an idle cluster — the opposite of what a generous
walltime is supposed to buy. The rate is ~7.4 min of work per run divided by PAR, and that rule
plus the measurements now sits in each sbatch file so the next job is sized from data.

The rebuild ran in 1:06:43 against the new 1:30 limit, so the sizing holds.

## 2. Rebuilt the old packs before measuring, not after

The 156-run job added the new signals to the uncovered families. The 136 older packs predated the
probe — including all 20 `normal` runs and every solved family.

Those are the negatives. **A signal missing from the negatives cannot be tested for separation at
all**: it would look as though the fault is the only family that has it, which is the most
convincing kind of wrong answer. Rebuilt with `--force` first.

Worth recording: my first attempt to add that flag silently failed — the shell collapsed the
backslash continuations so the patch matched nothing — and I submitted a job that would have
skipped every pack and reported success. Third time this session heredoc quoting has done that.

## 3. The result that corrects 8 September

**`service-memory-cap` does not separate.** I reported 16/16 with zero false fires. That was
measured against eight families that did not include `anomaly_mem`, its closest look-alike.

| `hardirq_x` | Sock Shop | Train Ticket |
|---|---|---|
| `svc_mem_cap` | 3.21 – 5.38 | 2.73 – 5.55 |
| `anomaly_mem` | 2.16 – 8.62 | 5.74 – 8.85 |

Host memory pressure raises device interrupts over the same range and higher. The shipped rule
would fire on it.

The arithmetic was never wrong. The negative set was too small, and a threshold validated against
a set that excludes its look-alike will always look good. `LATENCY-CAUSES` already states the rule
— check every new signal against ALL families — and this is the first time we have had the packs
to actually do it.

## 4. Two faults separate cleanly on both applications

`fork_storm` on `fork_newcomer_per_s > 26.34` (96.4/s against a 26.3 ceiling) and
`data_exfiltration` on `tx_newcomer_bytes_per_s > 3.64e6` (8.1e7 against 3.6e6, a 22x margin).
Both 10/10 with no false fires.

**Both recipes made predictions, and both were wrong in opposite directions.** fork_storm claimed
its signal was "unmistakable" — it is, but only as a newcomer; the host total moves 1.77x.
data_exfiltration doubted itself — *"the honest answer may be not from volume alone"* — and volume
alone does separate it, again as a newcomer rather than a host total.

Three faults now, one lesson: measure the arrival, not the level.

## 5. Four faults have no separating signal, and one of those is informative

`conn_pool_exhaustion`, `deadlock`, `resource_abuse` fail on everything tried; `anomaly_mem`
works on one application only.

`resource_abuse` failing on `thief_cores` matters: that signal gets `noisy_neighbor` 26/26. Both
faults run a hidden CPU loop, so a thief appears in both. The two are probably not separable FROM
EACH OTHER by CPU attribution. That is a finding about the pair, not a failure of the signal.

## 6. My own tool overstated three results

It printed "BAND TRANSFERS on both applications" whenever EACH application had a clean band. That
is a weaker claim than one band holding on both. `fd_exhaustion` genuinely has a shared band
(0.13 to 9.28, 7/7, no negatives inside); `priority_inversion` and `lock_contention` do not, and
were downgraded.

The same error the exercise exists to catch, made by the tool built to catch it.

## Still open

- Write the three blueprints that are ready: `fork_storm`, `data_exfiltration`, `fd_exhaustion`.
- Re-derive `service-memory-cap` against `anomaly_mem`, or record that the pair is inseparable.
- The four with no signal are a result to report, not a gap to hide.
- The with/without agent comparison on v2 is still not run.

---

# Blueprint cards (G1 from the 9 Sept meeting)

## Why the old charts never existed

All ten blueprints declared an `.svg` output. Two had chart code; eight had none. The two
used matplotlib inside a `try/except` that printed "chart skipped" and returned success.
Matplotlib is not on the cluster, so the chart never drew and the script never failed.

**Decision: write raw SVG from the standard library.** Nothing to install, nothing that can
silently skip. A picture that is allowed to fail quietly is worse than no picture, because
the declaration stays in the blueprint and reads as if it works.

## What the card shows, and why not a time series

A dashboard shows the number that moved. Naser was explicit that this is detection, not
root cause. So the card shows the decision instead, in three bands: where every fault sits
on the deciding axis, which gates passed and by how much, and what else was ruled out.

Band 1 is the one no other tool can draw. It needs every fault family measured on the same
axis - 272 runs, 25 families, two applications. From a single incident it is impossible.

No time axis, because the packs hold baseline-vs-incident aggregates and not a series.
That is honest on the card rather than faked. Fixing it is G2, and it is a pack change.

## Gates are now recorded, not just the final answer

Each rule was a chain of AND conditions that emitted only `fires` and a prose `why`.
Enough to score a run; not enough to show anyone why it landed there. Every condition now
records its name, value, bar, pass/fail and whether it is a veto. Purely additive - checked
all 7 rules still fire on their own families.

**The margin is the part that matters.** A gate passing at 1.3x its bar and one passing at
7.2x both log as PASS. Drawn side by side they look different, so a fragile gate is visible.

## The result that fell out of building it

Putting every run on one axis forced a comparison I had not planned: what the deciding
number does ALONE against what the whole rule does.

| Blueprint | number alone | whole rule |
|---|---|---|
| host-cpu-saturation | all 272 | 271/272 |
| data-exfiltration | all 272 | no rule yet |
| fork-storm / fd-exhaustion | 1 wrong | no rule yet |
| host-disk-saturation | 10 wrong | 262/272 |
| cpu-contention-co-tenant | 24 wrong | 271/272 |
| service-memory-cap | 25 wrong | 253/272 |
| network-path-degradation | 44 wrong | 268/272 |
| service-cpu-throttle | 68 wrong | 261/272 |
| db-latency-dependency-wait | 88 wrong | 241/272 |

**This is the argument for blueprints in one table.** For most faults one number is not
enough. Retransmission alone gets 44 wrong; with "was the baseline quiet" and "was the loss
in the queue" it gets 268 of 272 right. A threshold is not a blueprint, and now we can say
by how much.

## Two margins that are too thin to trust

The card names the closest other fault on every page. Two are alarming and were sitting in
the derivation files unnoticed:

- `service-cpu-throttle`: closest negative `svc_mem_cap` at 0.811 against a 0.80 cut. 1.4%.
- `db-latency-dependency-wait`: closest negative `anomaly_cpu` at 4.96 against 5.00. Under 1%.

Neither is a new measurement. What changed is that a picture put them next to each other.
`service-memory-cap` scoring 253/272 - the worst of the seven - is consistent with the
8 Sept finding that it does not separate from `anomaly_mem`.

## Cluster housekeeping

The cluster repo had 21 files staged but never committed, which blocked a pull. Checked
each by hash against `origin/blueprints` before touching anything: 19 identical, 2 older
copies (`blueprint_decide.py` predating the gates, `derive_v2_thresholds.py` still carrying
the BAND TRANSFERS bug). Nothing unique was on the cluster.

**Decision: do not do repo surgery for a one-minute job.** Sent the two scripts to
`~/cardgen` and ran them there. The cluster repo is untouched and still stale; that is a
separate cleanup, not something to bundle into a drawing task.

## Still open

- G2 early detection - needs a time series in the packs, which the card is already shaped
  to display once it exists.
- Three blueprints have no rule in the engine (`fork-storm`, `data-exfiltration`,
  `fd-exhaustion`). The cards say so on their face.
- The two thin margins above need re-deriving or recording as limits.
- Re-derive `service-memory-cap` against `anomaly_mem`, or record the pair as inseparable.
- The with/without agent comparison on v2 is still not run.
