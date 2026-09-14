# Full audit of v2 — every run, every directory

13 September 2026. Nothing sampled, nothing skipped.

Reproduce:
```bash
python3 microservice-lttng-data-collection-scripts/audit_dataset.py \
    --root /scratch/yuvraj17/stratatrace/data/stratatrace-v2 --out audit.json
python3 microservice-lttng-data-collection-scripts/audit_baselines.py \
    --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs
```

---

## The answer

**59 of 303 runs are not okay. 244 are fine.**

| | runs |
|---|---|
| **usable** | **244** |
| the injection did not take (`unconfirmed`) | 32 |
| the baseline is contaminated | 27 |
| **not usable** | **59** |

The two groups do not overlap at all — checked, zero runs in both. A run either failed to
inject or had its reference window spoiled, never both.

Nothing else is wrong. Every one of the 303 bundles is structurally complete: manifest,
checksums, ground truth, verification, a readable trace with metadata and channels, start and
end stamps, and an injection window that sits inside the traced window. All 303 metrics
sidecars exist and none is empty.

**One coverage gap to be honest about.** The baseline check needs an analysis pack, and 31
runs have none — `dependency_outage` (10), `error_storm` (16), `queue_backlog` (5). Their
baselines have not been checked at all. They are counted as usable above because nothing is
known against them, which is not the same as knowing they are fine.

---

## 1. The injection did not take — 32 runs

These carry `verification_status: unconfirmed`, meaning the campaign's own metric checks ran
and did not see the fault. The verdicts were written months ago; nothing had read them.

| family | app | bad / total |
|---|---|---|
| `slow_db` | Train Ticket | **10 / 11** |
| `svc_cpu_cap` | Train Ticket | **8 / 8** |
| `svc_net` | Train Ticket | 4 / 5 |
| `fd_exhaustion` | Sock Shop | 3 / 5 |
| `lock_contention` | Sock Shop | 3 / 5 |
| `error_storm` | Train Ticket | 2 / 8 |
| `deadlock` | Sock Shop | 1 / 5 |
| `svc_mem_cap` | Train Ticket | 1 / 8 |

Two of these are known and accepted: `svc_cpu_cap` does not bite on Train Ticket
(CAMPAIGN-ISSUES 12), and `slow_db` there is weak. Both were independently visible from the
kernel side.

## 2. The baseline is contaminated — 27 runs

The baseline window contains part of the fault, so every ratio computed against it is wrong.
Threshold: >10% retransmission in a window where a healthy run measures 0.00%.

| family | app | bad / total | cause |
|---|---|---|---|
| `code_n_plus_one` | Sock Shop | 5 / 5 | container restart inside the baseline |
| `code_lock_across_io` | Sock Shop | 5 / 5 | same |
| `code_serial_awaits` | Sock Shop | 5 / 5 | same |
| `code_event_loop_block` | Sock Shop | 5 / 5 | same |
| `code_unbounded_cache` | Sock Shop | 3 / 5 | same |
| `anomaly_net` | Sock Shop | 3 / 8 | netem applied before the stamp |
| `anomaly_net` | Train Ticket | 1 / 8 | same |

## 3. Warnings, not failures — 25 runs

- **16 `borderline`** — the effect is weak. Needs a human, not a re-run.
- **9 `no_metric_signature`** — no metric target can see the fault at all. **This is not a
  failed injection.** All 5 `dns_delay` runs read this way and 4 show the fault plainly in the
  kernel at 161–310 EMFILE/s. It is a fault metrics cannot detect and the kernel can.

---

## What was fixed as a result

### The ordering bug, in eleven recipes

`gt_begin` stamps the start of the incident window, so everything before it counts as baseline.
**Eleven recipes disrupted the system and then stamped**, putting their own ramp-up in the
baseline. `anomaly_net` was the measurable case — netem across 16–44 container namespaces
before the stamp, up to 50% baseline retransmission.

All eleven now stamp first. `faults/check_recipe_ordering.sh` enforces it and is meant to run
before any campaign.

### The checker took four attempts, and each failure is worth recording

| attempt | what it did | why it was wrong |
|---|---|---|
| 1 | scanned whole files | flagged code inside function definitions belonging to other branches — three correct recipes reported broken |
| 2 | ignored variable assignments | hid `N=$(apply_each add ...)`, which is a call |
| 3 | used a hand-written list of wrapper functions | missed `apply_each`, then missed `toxic_add` because the list said `add_toxic` |
| 4 | discovers wrappers from the file itself | works |

A list you have to remember to update is not a check.

### The same lesson bit the baseline audit

`endpoints vanishing between windows` looked like a clean corroborator — 3–7 gone in every
contaminated run against 1–2 in a clean one. Checked against every family, `anomaly_mem`,
`fd_exhaustion`, `fork_storm` and `nagle_delayed_ack` all reach 5 with quiet baselines. It is
now reported but decides nothing. Dropping it moved the count from 38 to **27**.

### A gate at the end of every run

`check_run_quality.py`, wired into `run_scenario.sh`: trace readable, injection window inside
the traced window, verification verdict, baseline quiet. Writes `run_quality.json` and exits
non-zero when a bundle is not usable. `verify_injection.py` is no longer wrapped in `|| true`.

---

## What still needs doing

1. **No analysis script reads `verification_status`.** 32 unconfirmed runs are being used as
   positives right now. This is the single highest-value fix left — CAMPAIGN-ISSUES 19.
2. **Re-collect the 27 contaminated runs** once a VM exists. The recipes are fixed but unrun.
3. **Decide about the 32 unconfirmed runs** — recalibrate the intensity, or record those faults
   as not reproducible on that application.

Before collecting anything: run `faults/check_recipe_ordering.sh`, then one
`code_n_plus_one` run, then confirm its baseline retransmission is 0.00%.
