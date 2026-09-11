# The 16 faults with no blueprint — which ones the kernel can actually tell apart

Measured 11 September 2026 across **all 303 runs and all 27 fault families**, so every family is a
negative for every other. Kernel traces only.

Cuts are placed against the other families' extreme, never fitted to the positives. A cut that
works on one application is reported as failing.

---

## First: a correction to the 8 September result

**`service-memory-cap` does not separate.** I reported it at 16/16 with zero false fires. That was
measured against a negative set of eight families that **did not include `anomaly_mem`** — host
memory pressure, its closest possible look-alike.

With all 27 families present:

| `hardirq_x` | Sock Shop | Train Ticket |
|---|---|---|
| `svc_mem_cap` (owns) | 3.21 – 5.38 | 2.73 – 5.55 |
| **`anomaly_mem`** | **2.16 – 8.62** | **5.74 – 8.85** |

Host memory pressure raises device interrupts over the same range as a container memory cap, and
higher. The rule as shipped would fire on it.

`fd_exhaustion` on Sock Shop also reaches 1.63–2.18, crossing the `IRQ_X = 2.0` bar.

Nothing was wrong with the arithmetic. The negative set was too small, and a threshold validated
against a set that excludes its look-alike will always look good. `LATENCY-CAUSES` already states
the rule — *every new signal has to be checked against all families, not just its own* — and this
is the first time we have had the packs to actually do it.

---

## Two faults separate cleanly, on both applications

### `fork_storm` — `fork_newcomer_per_s > 26.34`

| | Sock Shop | Train Ticket |
|---|---|---|
| forks/s gained by the newcomer | 96.36 | 96.22 |
| highest of any other family | 22.42 | 26.34 |

**10/10, no false fires.** The host total also works (`forks_per_s_x > 1.226`) but with far less
margin — 1.51–1.77 against a 1.23 ceiling.

The recipe predicted this signal would be "unmistakable". It is, but only as a **newcomer**. The
host already forks 134 times a second, so the total moves 1.77× while the arriving process moves
27×.

### `data_exfiltration` — `tx_newcomer_bytes_per_s > 3.64e6`

| | Sock Shop | Train Ticket |
|---|---|---|
| bytes/s gained by the newcomer | 8.11e7 | 8.11e7 |
| highest of any other family | 1.98e6 | 3.64e6 |

**10/10, no false fires**, with a 22× margin.

**This disproves the recipe's own pre-registered doubt.** It said *"the honest answer may be 'not
from volume alone'"*. Measured, volume alone does separate it — provided you measure the process
that arrived rather than the host total, which is one-app-only (`tx_bytes_per_s_x`: 6.2–6.3× on
Sock Shop, 24.9–25.0× on Train Ticket).

---

## One fault needs a band, and the band holds on both

### `fd_exhaustion` — `emfile_per_s` between 0.13 and 9.28

7/7 confirmed positives inside, no negative inside. A band rather than a cut because something
else on Sock Shop reaches 310 EMFILE/s, far above the fault itself.

The fault's own rate differs 5× between applications — Sock Shop 0.27–1.78, Train Ticket
8.52–8.65 — which is why a one-sided cut fails and a band works.

Caveat: only **2 of 5** Sock Shop runs are campaign-confirmed, so this rests on 2 + 5 runs.

---

## Two have a band per application but no shared band

`priority_inversion` (`prio_non_default_pct`: 0.43–0.44 on Sock Shop, 1.59–1.71 on Train Ticket)
and `lock_contention` (`futex_short_waits_x`: 1.23–1.24 against 2.61–2.71) are each cleanly
separable **within** an application, and there is no single band covering both.

That is a weaker result than it first appeared. My tool originally reported these as "BAND
TRANSFERS", which was wrong: it fired when each application had its own band, not when one band
held both. Fixed, and the two claims were downgraded.

They are still usable — with a per-deployment reference rather than a shipped constant, which is
what `profile_decide.py` does.

---

## Four faults do not separate on anything we measured

| fault | signals tried | outcome |
|---|---|---|
| `conn_pool_exhaustion` | ECONNREFUSED/s, ETIMEDOUT/s, error newcomer | none separate |
| `deadlock` | futex p95, futex wait, futex short waits | none separate |
| `resource_abuse` | thief cores, tx newcomer | none separate |
| `anomaly_mem` | hardirq, disk arrivals, total iops | Train Ticket only |

**`resource_abuse` failing on `thief_cores` is the interesting one.** That signal gets
`noisy_neighbor` 26/26. Both faults run a hidden CPU loop, so a thief appears in both — meaning
the two are probably **not separable from each other** by CPU attribution. That is a finding about
the fault pair, not a failure of the signal.

`deadlock` and `lock_contention` were expected to split on futex *shape* — many short waits for
contention, a stretched tail for deadlock. Contention shows the shape; deadlock does not separate
from anything.

`dns_delay` could not be tested for transfer at all: 5 runs, Sock Shop only, because Train Ticket
makes no DNS queries.

---

## Where this leaves the library

| | families | runs |
|---|---|---|
| blueprint exists and holds on both apps | 4 | 62 |
| **ready to write now** (`fork_storm`, `data_exfiltration`, `fd_exhaustion`) | **3** | **25** |
| separable per application only | 2 | 20 |
| no separating signal found | 4 | 46 |
| out of scope (kernel cannot see it) | 3 | 31 |
| `service-memory-cap` — needs re-deriving against `anomaly_mem` | 1 | 16 |

## Reproducing

```bash
python blueprints/lib/v2_tasks.py --families all --out blueprints/lib/tasks-v2-everything.txt
python blueprints/lib/derive_v2_thresholds.py \
    --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
    --tasks blueprints/lib/tasks-v2-everything.txt
```

Positives the campaign could not confirm are excluded by default, which is why some families show
n=2 — `fd_exhaustion` and `lock_contention` are 2/5 confirmed on Sock Shop.
