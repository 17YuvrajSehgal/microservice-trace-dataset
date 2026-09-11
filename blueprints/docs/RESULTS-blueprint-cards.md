# Blueprint cards — a picture per blueprint

Written 11 Sept 2026. Answers **G1** from the 9 Sept meeting.

Naser asked for a picture for each problem, drawn from the trace with Babeltrace, not
Trace Compass. All ten blueprints already promised an `.svg`. None of them drew one.

Now all ten draw one. Files: `blueprints/problems/<id>/evidence/<id>_card.svg`.

---

## Why the old charts never appeared

Two blueprints had chart code. Both used matplotlib, wrapped like this:

```python
try:
    fig.savefig(a.chart)
except Exception as e:
    print(f"chart skipped: {e}")
```

Matplotlib is not installed on the cluster. So the chart was skipped, the script still
said OK, and nobody noticed for months.

The new drawing code uses **no libraries at all**. It writes SVG text directly. There is
nothing to install and nothing to skip.

---

## What is on a card

Three bands. The point is to show the **decision**, not the measurement.

### Band 1 — the ruler

Every fault family we have measured, placed on the one number this blueprint decides on.
Two lanes, one per application. The cut is drawn as a red line.

You can read four things straight off it:

- how big a gap the blueprint is relying on
- **which other fault comes closest to breaking it**, by name
- whether the cut lands the same way on Sock Shop and on Train Ticket
- where this particular run sits

Nobody can draw this from one incident. It needs 272 labelled runs across 25 families on
two applications, which is what the dataset is for.

### Band 2 — the gates

Every condition the rule tested: the measured number, the bar it had to clear, pass or
fail, and **how much room it had**.

This matters. A gate that passed at 1.3x its bar and one that passed at 7.2x both read
"PASS" in the log. On the card they look different, so you can see which part of a rule
is fragile.

Veto gates are drawn in amber, because a veto is a different kind of claim from a
requirement.

### Band 3 — the field

The other six blueprints, and the single number that ruled each one out.

Ruling out is most of what root-cause work actually is. Naser's point was that "the system
is under contention" is detection, not root cause. This band is where the card earns the
difference.

---

## The result that came out of building it

Each card compares two things: what the deciding number does **on its own**, and what the
**whole rule** does. That was not the plan; it fell out of putting all the runs on one axis.

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

**Read the two columns together.** For most faults one number is not enough. Retransmission
alone gets 44 runs wrong; add "was the baseline quiet" and "was the loss in the queue" and
it gets 268 of 272 right. A socket wait alone gets 88 wrong; the full datastore rule gets
241 right.

That is the argument for blueprints in one table. A threshold is not a blueprint. The extra
gates are doing the work, and now we can show exactly how much.

---

## Which fault nearly breaks each blueprint

The card names this on every page. Collected here:

| Blueprint | Closest other fault | Its value | The cut |
|---|---|---|---|
| service-memory-cap | code_serial_awaits (Sock Shop) | 1.72 | 2.00 |
| host-cpu-saturation | noisy_neighbor (Sock Shop) | 0.889 | 0.95 |
| service-cpu-throttle | svc_mem_cap (Sock Shop) | 0.811 | 0.80 |
| db-latency-dependency-wait | anomaly_cpu (Sock Shop) | 4.96 | 5.00 |
| host-disk-saturation | svc_mem_cap (Train Ticket) | 352.4 | 450 |
| network-path-degradation | noisy_neighbor (Sock Shop) | 11.1 | 12.0 |
| cpu-contention-co-tenant | slow_db (Sock Shop) | 0.362 | 0.50 |
| fork-storm | slow_db (Sock Shop) | 22.4 | 26.34 |
| data-exfiltration | svc_mem_cap (Train Ticket) | 3.64 MB/s | 3.64 MB/s |

Two of these are uncomfortably tight:

- **service-cpu-throttle**: 0.811 against a 0.80 cut. A 1.4% margin. A memory cap is one
  rounding error away from being called a CPU quota.
- **db-latency-dependency-wait**: 4.96 against 5.00. Under 1%.

The rest have room. `host-cpu-saturation` at 0.889 against 0.95 is about 7%, which is
comfortable for a saturation measure that tops out at 1.0.

`data-exfiltration` looks alarming in the table and is not. Its cut was deliberately placed
**at** the highest other fault, so the two are equal by construction; the real margin is the
22x gap up to the lowest positive at 81 MB/s.

All of these numbers already existed in the derivation files. Nobody had put them side by
side, because there was no picture to put them in.

---

## Honest limits

- **A card shows one signal per blueprint**, chosen as the one its rule decides on. A rule
  with six gates has five other numbers not on the ruler. Band 2 covers them, but without
  the family-by-family spread.
- **Three blueprints have no gates to show** — `fork-storm`, `data-exfiltration` and
  `fd-exhaustion` are measured and written up, but the rule engine has no rule for them.
  The card says so on its face rather than drawing a decision the code cannot make.
- **No time axis yet.** The packs hold baseline-vs-incident aggregates, not a series. So
  the card cannot yet show when the signal crossed. That is **G2, early detection**, and it
  needs a change to the pack builder, not to the card.
- The per-application lanes use whatever runs exist. Train Ticket has fewer families than
  Sock Shop, so some lanes are thinner.

---

## How to make them

The ruler is built once, on the cluster, over every pack:

```bash
python3 blueprints/lib/build_ruler.py \
  --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
  --out blueprints/results/ruler.json
```

Takes under a minute. Then the cards, anywhere:

```bash
python3 blueprints/lib/make_cards.py --packs <packs> --ruler blueprints/results/ruler.json
```

`build_ruler.py` re-uses the same extractor functions the rules use rather than re-reading
the packs its own way. If it did its own reading, the picture could drift away from the
decision, which is the one thing a picture like this must never do.

---

## One more thing the cards carry

Every card has a plain-text `<desc>` inside the SVG with the same three bands written out.
So an agent that opens the file gets the story without needing to see the picture. The
picture is for us; the text is for the agent. Same file, no second artifact to keep in sync.
