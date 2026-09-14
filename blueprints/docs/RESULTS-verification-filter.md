# Reading the campaign's own verdict — what changed

13 September 2026. Closes CAMPAIGN-ISSUES 19.

283 of 303 v2 runs carry a `verification_status` written at collection time by
`verify_injection.py`. **No analysis script read it.** So runs whose fault demonstrably did not
take were used as positives when deriving thresholds and as labelled examples when measuring
separation.

---

## The headline

| | every labelled run | only runs whose fault took |
|---|---|---|
| runs a blueprint owns | 116 | **91** |
| **correct** | **85 (73%)** | **82 (90%)** |
| missed | 31 | **9** |
| runs that should produce no verdict | 156 | **181** |
| **false fires** | **46** | **49** |

**Both numbers move, in opposite directions, and that is the honest result.**

- Recall goes 73% → **90%**. Twenty-two of the thirty-one "misses" were not misses: there was
  no fault in the run to find.
- False fires go 46 → **49**. Three runs where a blueprint fired were being counted as *hits*
  because the run carried a fault label. The fault did not take, so firing on them is a false
  fire.

Dropping those runs from both columns would have improved the score by deleting the evidence.
They are excluded as positives and **kept as negatives**.

---

## The policy, and why each part

| status | as a positive | as a negative |
|---|---|---|
| `confirmed` | yes | yes |
| `unconfirmed` — the checks ran and saw nothing | **no** | **yes** |
| `no_metric_signature` — no metric target can see this fault | yes, if the kernel shows it | yes |
| `borderline` — weak effect | no, and counted separately | yes |
| `unknown` — the 20 healthy controls | n/a | yes |

**Keeping them as negatives is the part that matters.** A run in which nothing happened is
still a real run, and a blueprint firing on it is a real false fire. Removing it would make
every separation look better than it is.

`no_metric_signature` is not a failed injection — all 5 `dns_delay` runs read that way and 4
show the fault plainly in the kernel at 161–310 EMFILE/s.

---

## Which families were being scored against runs with no fault

| app | family | scored before | scored now |
|---|---|---|---|
| Train Ticket | `slow_db` | 1 / 11 | **0 / 0** |
| Train Ticket | `svc_cpu_cap` | 0 / 8 | **0 / 0** |
| Train Ticket | `svc_net` | 1 / 5 | **0 / 0** |
| Train Ticket | `svc_mem_cap` | 7 / 8 | 6 / 7 |

Three Train Ticket families have **no verified run at all**. Every previous number for them was
measured against runs whose fault did not take. `svc_cpu_cap` scoring "0/8" was never a
blueprint failure — there was nothing in those eight runs to find.

## And two families have no verified run anywhere

The sweep of uncovered families now reports this instead of deriving a threshold:

- `code_lock_across_io` — 0 of 5 confirmed
- `code_n_plus_one` — 0 of 5 confirmed

Deriving a cut from runs that contain no fault would be fitting to noise. The sweep says so and
stops.

---

## What changed in the code

| file | change |
|---|---|
| `lib/verification.py` | new. The index, the policy, and a `report()` every caller prints |
| `results/verification_index.json` | run → status for all 303 runs, committed |
| `lib/build_ruler.py` | every ruler point carries its status |
| `lib/sweep_uncovered.py` | positives filtered; a family with no verified run says so |
| `lib/score_with_verification.py` | new. Scores both ways, side by side |

Every script that filters **prints what it filtered**. A filter nobody can see is how the
original silence happened.

---

## One thing the filter does not fix

`dns_delay` now reports "no signal separates it" in the sweep, because the sweep requires
*every* positive to clear the cut and `r4` measures EMFILE at exactly zero — its injection did
not take, but its status is `no_metric_signature`, which the policy lets through.

The status cannot tell "metrics are blind to this fault" from "nothing happened" — only the
kernel can, and the sweep is the thing measuring the kernel. The `dns-delay` blueprint records
the honest version: 4 of 5, with the fifth named as a failed injection.
