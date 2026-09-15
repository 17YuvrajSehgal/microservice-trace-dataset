# 15-09-2026 — decisions

## 1. Re-collected all 5 code-defect families on the new VM (25 runs, all usable)

The old runs were contaminated: the recipe restarted the container to inject the
defect, so the "baseline" contained a container restart. Baseline TCP
retransmission was 34.7–79.9%.

The fix (issue 17) splits the recipe into `arm` (restarts, before tracing) and
`inject` (writes a flag, no restart). Re-collected 5 runs per family.

**Result: 26 of 26 runs usable.** (25 campaign runs + 1 earlier proof run.)

## 2. Two of the five defects DO have a metric signature. Three do not.

This is the main finding of the session, and it reverses what I wrote earlier
today. I had claimed no Prometheus series moves for any code defect. That holds
for three families, not five.

Catalogue request rate, per family (requests/s, median of 5 runs):

| family | baseline | injection | recovery | reads as |
|---|---|---|---|---|
| `code_lock_across_io` | 106.5 | 262.2 | 262.7 | ramp only |
| `code_n_plus_one` | 104.1 | 255.9 | 255.0 | ramp only |
| `code_unbounded_cache` | 99.8 | 245.9 | 247.2 | ramp only |
| `code_event_loop_block` | 102.8 | **34.3** | **122.4** | real |
| `code_serial_awaits` | 93.6 | **50.5** | **132.4** | real |

**The recovery column is the control.** Where the fault is invisible, injection
and recovery are the same number — the rise is the load generator spinning up
(issue 20) and it never comes back down. Where the fault is real, the rate falls
during injection and returns afterwards. The container image is identical across
both windows. Only the `/dev/shm` flag changed.

**Why these two.** Both are front-end Node defects. The event loop is
single-threaded, so blocking it stalls every request and catalogue stops being
called. The three invisible ones are Go in catalogue, where concurrency absorbs a
per-request slowdown and offered throughput is unchanged.

This is a useful result for the modality study: metrics see a defect when it
blocks a single-threaded loop, and miss it when the runtime absorbs it. Same
class of bug, opposite modality outcome.

### What changed in the targets

- `code_event_loop_block`, `code_serial_awaits`: canonical target
  `catalogue_throughput_drop`, `expected_to_fail` removed. They verify normally.
- The other three keep `expected_to_fail` → `no_metric_signature`.

`expected_to_fail` handled the surprise correctly on its own: a target marked
expected-to-fail that passes anyway yields `confirmed`, not an error. The
mechanism found this, I did not.

### Caveat recorded, not resolved

The sigma test fails on the two visible families (`sigma_ok=false`) because the
baseline window includes the load ramp, which inflates `baseline_std`. The
verdict rests on direction + fraction, corroborated by recovery. This is another
consequence of issue 20.

Also open: settled catalogue rate is ~130/s in front-end-defect runs but ~250/s
in catalogue-defect runs, under the same load profile. Within-run comparison is
unaffected, but absolute rates should not be compared across the two groups until
this is explained.

## 3. Why the earlier `no_targets` approach was wrong

Deleting the targets produced `no_targets`, which means "nothing registered to
check" — a harness gap for an operator to fix. What we know is stronger: we
checked, and metrics cannot see three of these faults.

`verify_injection` already had the right mechanism, `expected_to_fail`, with
`dns_delay` as the precedent. Reused it instead of inventing a second path.
