# Next steps, as of 22-09-2026 late evening

## Running right now

| | where | state |
|---|---|---|
| `anomaly_net` re-run, corrected recipe | `results/q2-net-ss`, `results/q2-net-tt` | 21/120 cells |
| line samples (the 80% speedup) | SLURM `ctflines`, staging at `dataset/index-staging/` | building, 66 runs |

**Install the line samples only when no matrix is running:**

    mv /scratch/yuvraj17/stratatrace/dataset/index-staging/*.lines.gz \
       /scratch/yuvraj17/stratatrace/dataset/index/

Dropping them in while cells are live changes `ctf_lines` underneath the experiment - half the
cells get a different cost and a different sample.

## Do next, in this order

**1. Finish the `anomaly_net` story.** When the 120 cells land, compare `q2-net-ss` against
`q2-full`/`q2-ss2` for that problem only. That answers whether "the blueprint hurts window
finding" was entirely my false recipe or only mostly.

**2. Decide whether to revert the prompt change.** It cost `noisy_neighbor` 5 points (WHERE
20/30 -> 15/30 in the control arm, `ambiguous` 1 -> 8) and did not fix what it targeted. Its
effect and the recipe's are currently confounded; decide on a run where the recipe is correct.

**3. Raise `--jobs` once the line samples are installed.** Cells are CPU-bound in babeltrace
today - 11 running, 11 in babeltrace, 11 of 192 cores. After the samples they become API-bound,
and 12-16 jobs should be safe. A 360-cell matrix ought to go from ~10 h to under an hour.

**4. Run the 11-problem matrix.** `PROBLEMS` now holds 11, up from 6. That is 11 x 3 x 2 x 2 x
5 = 660 cells per application. Only worth starting after step 3.

## Known-open, with the evidence already gathered

**`slow_db` inverts across applications and nobody knows why.** Sock Shop finds the place (40%)
and not the time (5%); Train Ticket finds the time (53%) and not the place (5%). Both n=60, so
it is not noise. Read `results/q2-tt/review/review-slow_db.md` against the Sock Shop one.

**`svc_net` and `svc_cpu_cap` are 0% on both applications.** Replicated, so not a Sock Shop
quirk - but we know the trace carries `pid_ns` and `sched_stat_runtime`, so part of this is
still our tooling and not the modality.

**Two index fields would settle two open questions**, and both are the same shape as the
`ctf_lines` problem - the data is in the trace and the index discards the field:

- `sched_switch.prev_prio/next_prio` would likely make `priority_inversion` decisive. Today it
  rests on two weak secondary shares (softirq 13.4% vs 5.9%, migrate 2.0% vs 5.0%).
- summed `sched_stat_runtime.runtime` per container would make `svc_cpu_cap` solvable. Measured
  by hand: carts sits at 0.195 CPU-s/s against a 0.200 cap - pinned at the ceiling, invisible to
  a count-based index.
- a `seq`-repeat counter over `net_if_receive_skb` would make `anomaly_net` properly answerable
  rather than only confirmable.

**`anomaly_mem` cannot be told from `noisy_neighbor` from kernel traces.** on-CPU 34.0 / softirq
42.8 against 27.0 / 35.7. The profile records no `mm_` or reclaim events at all. This is the one
case so far where the honest answer is that we need metrics - worth being the first
cross-modality result.

## Not started

- the `chosen` arm, where the agent picks its own blueprint from all 16. Until it exists the
  `fault` column measures reading comprehension.
- human review of the 60-run review sheets. `results/*/review/review-<problem>.md`.
- `blueprints/docs/SOCK-SHOP-RESULTS-22-09-2026.md` still reports `q2-full`, which used the old
  prompt AND the false recipe. Regenerate from `q2-ss2` + the `anomaly_net` re-run.
