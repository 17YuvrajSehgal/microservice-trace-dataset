# What needs re-collecting on a VM

13 September 2026. Measured over all 272 v2 packs.

The check: for each run, does its **own fault's** deciding signal sit inside the healthy range
for that application? If it does, the label says one thing and the trace shows nothing.

---

## The short answer

**31 runs need re-collecting. 30 more cannot be assessed without new collection.**

Nothing else does. The rest of the dataset is sound.

---

## 1. Must re-collect — the injection was wrong

### The five code-defect families — 25 runs, Sock Shop

Contaminated baselines. The injection restarted the container inside the baseline window, so
28–80% retransmission sits in a window that should read 0.00%. Every baseline-relative ratio in
these runs is measured against a container teardown.

| family | runs |
|---|---|
| `code_event_loop_block` | 5 |
| `code_lock_across_io` | 5 |
| `code_n_plus_one` | 5 |
| `code_serial_awaits` | 5 |
| `code_unbounded_cache` | 5 |

**The recipes are fixed** (CAMPAIGN-ISSUES 17) — `arm` before tracing, `inject` writes one word,
no restart inside the window. Not yet run on hardware, because there is no hardware.

### `svc_net` on Train Ticket — 4 runs

Only 1 of 5 produced packet loss (42.9%). The other four measure 0%.

| run | retransmission | endpoint slowdown | verdict |
|---|---|---|---|
| r1 | 42.9% | 1587x | good |
| r3 | 0% | 208x | something happened, but not loss |
| r4 | 0% | 983x | same |
| **r2** | **0%** | **none** | **inert** |
| **r5** | **0%** | **none** | **inert** |

r2 and r5 contain nothing. r3 and r4 need a decision: if the recipe is meant to cause loss, they
are miscalibrated; if latency is acceptable, they are usable and the blueprint needs widening.

### Two single runs

| run | what happened |
|---|---|
| `dns_delay_aggressive_steady_r4` | EMFILE exactly 0, DNS rate flat. The injection did not take |
| `tt_slow_db_subtle_steady_r3` | no endpoint slowed, no socket wait. Nothing happened |

---

## 2. Cannot be assessed without new collection — 30 runs

These faults exist on **one application only**, so transfer can never be checked.

| family | runs | why |
|---|---|---|
| the five `code_*` families | 25 | the defect images were written against Sock Shop's services |
| `dns_delay` | 5 | Train Ticket resolves nothing by name — this one may be impossible |

Building Train Ticket defect images is real work. It is also the only way any of those five
faults can ever satisfy the two-application rule.

---

## 3. NOT a collection problem, though it looks like one

This is where I nearly got it wrong, twice, and the correction matters.

### `svc_cpu_cap` on Train Ticket — 8 runs

Host CPU **rises** (1.03–1.065x) when a quota should make it fall. By the host-level signal all
eight runs look inert.

They are not. Endpoint latency is 11.8–216x with slowed endpoints in every run. **The cap is
biting one service; it just does not move a 16-core host running forty of them.**

### `slow_db` on Train Ticket — 10 runs

By socket wait, 9 of 11 look inert. By endpoint latency they measure **10.3x to 4836x**, and 10
of 11 have slowed endpoints.

The reason is already recorded: Train Ticket reports all forty Java services under one process
name, so one blocked service is averaged into thirty-nine idle ones. The endpoint measurement
keys on address and port, so it sees what the process view cannot.

**Both of these are analysis problems.** Re-collecting would not help unless the services were
made distinguishable at process level — which is a deployment change, not a longer run.

---

## What I would do, and in what order

1. **Nothing until a VM exists.** All of this needs one.
2. **First run back: one `code_n_plus_one` run**, then check baseline retransmission is 0.00%.
   That single number tells you whether the recipe fix works. Do not collect 25 runs before
   checking one.
3. **Then the 25 code-defect runs**, and `svc_net` on Train Ticket with a calibrated intensity.
4. **The four single runs** (`dns_delay` r4, `tt_slow_db_subtle` r3, `svc_net` r2/r5) come free
   with the above.
5. **Train Ticket code defects are a separate decision** — real work, and worth it only if we
   want those five faults in the paper.

## A method note

My first pass at this reported **22 inert runs**. The real number is **4**.

Eighteen of those twenty-two were the *fault being present and my chosen signal being the wrong
instrument for that application*. It is the same mistake as testing "the slowest endpoint"
across families, and the same mistake as requiring a two-application cut for a fault that only
exists on one.

**A run is not inert because our signal missed it.** Check with a second instrument before
calling data bad — the cost of being wrong here is re-collecting runs that were fine.

---

# CORRECTED 13 Sept, same day — the campaign already knew

Everything above was written from the kernel side only. Then I read the campaign's own
verification, which I had wrongly reported as missing. **283 of 303 runs carry a verdict**
(the other 20 are the `normal` controls, skipped by design), and it had already flagged every
run I "found".

| verification_status | runs |
|---|---|
| `confirmed` | 226 |
| `unconfirmed` | 32 |
| `borderline` | 16 |
| `no_metric_signature` | 9 |

## The distinction I got wrong, and it matters

`no_metric_signature` is **not** a failed injection. It means no metric target could see the
fault at all.

**All 5 `dns_delay` runs are `no_metric_signature`. Four of them show the fault plainly in the
kernel trace, at 161–310 EMFILE/s.**

That is a fault the metric modality cannot detect and the kernel modality can, measured rather
than argued — and it arrived as a by-product of checking why a run looked inert. It is now
recorded on the `dns-delay` blueprint.

`unconfirmed` is the one that means "the checks ran and did not see the fault".

## Which families the campaign says are weak

| family | confirmed | rest |
|---|---|---|
| `slow_db` | 11 / 22 | 10 unconfirmed, 1 borderline |
| `svc_cpu_cap` | 8 / 16 | 8 unconfirmed — all Train Ticket |
| `svc_net` | 5 / 10 | 4 unconfirmed, 1 borderline |
| `code_n_plus_one` | 0 / 5 | 5 borderline |
| `code_lock_across_io` | 0 / 5 | 5 borderline |
| `dns_delay` | 0 / 5 | 5 `no_metric_signature` — see above |
| `fd_exhaustion` | 7 / 10 | 3 unconfirmed |
| `lock_contention` | 7 / 10 | 3 unconfirmed |

This confirms the kernel-side findings independently: `svc_cpu_cap` on Train Ticket and
`slow_db` on Train Ticket are weak in the metrics too.

## What actually changed as a result

1. **A quality gate now runs at the end of every collection** —
   `check_run_quality.py`, wired into `run_scenario.sh`. It checks the trace is readable, the
   injection window sits inside the traced window, the verification verdict, and that the
   baseline is quiet. Writes `run_quality.json` and says loudly when a bundle is not usable.
2. **`verify_injection.py` no longer fails silently.** It was wrapped in `|| true`, so a crash
   produced no verdict and a run with no verdict looked the same as one that passed.
3. **The analysis still ignores `verification_status`** — that is CAMPAIGN-ISSUES 19 and it is
   open. `dns_delay` should be scored 4/4 on runs that contain the fault, not 4/5.

## The honest summary of my own error rate here

Three claims in this document's first version were wrong, all in the same direction — treating
a signal that did not fire as evidence that something was broken:

- "22 inert runs" — the real number is 4.
- "`verification.json` does not exist anywhere" — 283 of them do. My search was broken.
- "these four runs are a new discovery" — the campaign had flagged all four months earlier.

The pattern is the same every time: **a check returning nothing is not a finding until the
check itself has been verified.**
