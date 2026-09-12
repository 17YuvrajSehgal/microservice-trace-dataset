# Blueprint cards — one analysis page per blueprint

Written 11 Sept 2026. Answers **G1** from the 9 Sept meeting.

Files: `blueprints/problems/<id>/evidence/<id>_card.svg`. All ten exist.

---

## What Naser asked for, and where we stand

His words at 1:22:

> "Use Babeltrace to just create some graph for each part. Then see how you can show them,
> like a **timeline**, **resources**, **waiting**, or sometimes it can be just a **CPU
> usage**, when CPU goes up."

| His word | On the card |
|---|---|
| resources | **Yes** — panel B, CPU per process |
| waiting | **Yes** — panel C runqueue delay, panel D syscall blocking |
| CPU usage | **Yes** — panel B, plus the host figure in the gates |
| timeline | **No.** See below |

**The timeline is the one real gap.** The packs hold baseline-vs-incident totals, not a
series, so there is no time axis to draw. Drawing one from two points would be a lie. Getting
a real one means a new pass over the traces — that is **G2, early detection**, and it needs a
change to the pack builder, not to the card.

The card says this on its own footer rather than hiding it.

---

## Why the old charts never appeared

Two blueprints had chart code. Both used matplotlib wrapped like this:

```python
try:
    fig.savefig(a.chart)
except Exception as e:
    print(f"chart skipped: {e}")
```

Matplotlib is not on the cluster. The chart was skipped, the script still reported OK, and
nobody noticed. The new code writes SVG text directly — no library, nothing that can skip.

---

## The six panels

No decoration. Plain type, one accent colour, thin rules. It is for reading, not for looking
at.

**A — the deciding signal, every run we have.** All 272 runs on the one number this blueprint
decides on, both applications as separate lanes, the cut as a dashed line. This is the panel
nobody else can draw: it needs every fault family measured on the same axis.

It reports three things in words underneath:
- the nearest other fault to the cut, by name, with the margin
- what this signal does **on its own**
- what **every gate together** does

**B — resources.** CPU held by each process, baseline against incident.

**C — waiting for CPU.** Runqueue delay per service.

**D — waiting on something else.** Time blocked in a syscall, per process and call.

B, C and D are dumbbells: hollow dot is baseline, filled dot is during the fault, on a log
axis. Log because the ratios run from 1x to 5000x; a linear axis shows one spike and six flat
lines.

Rows are sorted by **absolute change**, not by ratio. Ratio puts a process that went from
0.0003 to 0.03 cores at the top — a 100x rise that means nothing — and buries the service that
actually moved. The ratio is still printed on every row. A process with no baseline reads
**new**, which is usually the most interesting row on the panel.

**E — gates.** Every condition the rule tested: value, bar, margin, pass or fail.

**F — the field.** The other blueprints and the one number that ruled each out.

---

## What the cards show at a glance

Two examples, both straight off the page.

**`cpu-contention-co-tenant` on a noisy-neighbour run.** Panel B shows `stress-ng-cpu`
arriving **new** with 2.0 cores. Panel C shows seven services all waiting 3.5–9.6x longer for
CPU. That is the whole fault in two panels.

**`service-memory-cap`.** Panel B shows `python3` at 2.56x and three `conn*` processes
arriving new. Panel D shows `java|poll` at 78x and `java|read` at 62x. Reclaim inside one
cgroup, and the services stalling behind it.

---

## The result that came out of building it

Each card compares the deciding number **alone** against the **whole rule**. That was not
planned; it fell out of putting all the runs on one axis.

| Blueprint | This number alone | The whole rule |
|---|---|---|
| host-cpu-saturation | separates all 272 | **271 / 272** |
| data-exfiltration | separates all 272 | no rule yet |
| fork-storm | 1 wrong | no rule yet |
| fd-exhaustion | 1 wrong | no rule yet |
| host-disk-saturation | 10 wrong | **262 / 272** |
| cpu-contention-co-tenant | 24 wrong | **271 / 272** |
| service-memory-cap | 25 wrong | 253 / 272 |
| network-path-degradation | 44 wrong | **268 / 272** |
| service-cpu-throttle | 68 wrong | 261 / 272 |
| db-latency-dependency-wait | 88 wrong | 241 / 272 |

**Read the columns together.** For most faults one number is not enough. Retransmission alone
gets 44 runs wrong; add "was the baseline quiet" and "was the loss in the queue" and it gets
268 of 272 right.

That is the argument for blueprints in one table. A threshold is not a blueprint, and now we
can say by how much.

---

## Which fault nearly breaks each blueprint

The card names this on every page, with the margin.

| Blueprint | Closest other fault | Its value | The cut | Margin |
|---|---|---|---|---|
| db-latency-dependency-wait | anomaly_cpu (Sock Shop) | 4.96 | 5.00 | **1.01x** |
| service-cpu-throttle | svc_mem_cap (Sock Shop) | 0.811 | 0.80 | **1.01x** |
| host-cpu-saturation | noisy_neighbor (Sock Shop) | 0.889 | 0.95 | 1.07x |
| service-memory-cap | code_serial_awaits (Sock Shop) | 1.72 | 2.00 | 1.16x |
| network-path-degradation | noisy_neighbor (Sock Shop) | 11.1 | 12.0 | 1.08x |
| cpu-contention-co-tenant | slow_db (Sock Shop) | 0.362 | 0.50 | 1.38x |
| host-disk-saturation | svc_mem_cap (Train Ticket) | 352.4 | 450 | 1.28x |
| fork-storm | slow_db (Sock Shop) | 22.4 | 26.34 | 1.17x |

The top two have about 1% of room. A memory cap is one rounding error from being read as a
CPU quota, and a CPU fault is one from being read as a slow datastore.

`data-exfiltration` is not in the table because its cut was placed **at** the highest other
fault by construction; its real margin is the 22x gap up to the lowest positive at 81 MB/s.

These numbers all existed in the derivation files. Nobody had put them side by side, because
there was no picture to put them in.

---

## Honest limits

- **No time axis.** Stated above and on the card itself.
- **One signal per ruler.** A rule with six gates has five other numbers not on panel A.
  Panel E covers them, but without the family-by-family spread.
- **Three blueprints have no gates** — `fork-storm`, `data-exfiltration`, `fd-exhaustion` are
  measured and written up, but the rule engine has no rule for them. The card says so.
- **Every card's example run is Sock Shop**, because that is which packs were downloaded.
  The ruler behind it covers both applications, so the comparison is sound, but the worked
  example is one application each time.
- **Nothing rebuilds these automatically.** No CI, no hooks. They are a snapshot. If a
  threshold moves in `blueprint_decide.py`, the drawn cut is wrong until someone re-runs.

---

## How to make them

Build the ruler once, on the cluster, over every pack:

```bash
python3 blueprints/lib/build_ruler.py \
  --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
  --out blueprints/results/ruler.json
```

Under a minute. Then the cards, anywhere:

```bash
python3 blueprints/lib/make_cards.py --packs <packs> --ruler blueprints/results/ruler.json
```

`build_ruler.py` re-uses the same extractor functions the rules use rather than reading the
packs its own way. If it read them separately, the picture could drift away from the decision.

---

## One thing the cards carry for the agent

Every card has a plain-text `<desc>` inside the SVG — 30 to 40 lines, covering all six panels
including every dumbbell row. An agent that opens the file gets the numbers without needing to
see the picture. Same file, nothing extra to keep in sync.
