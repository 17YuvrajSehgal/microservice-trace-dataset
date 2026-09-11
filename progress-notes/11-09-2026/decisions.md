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
