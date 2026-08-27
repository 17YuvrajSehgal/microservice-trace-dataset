# Blueprint vs the alternatives — 12 incidents, same data, same scorer

Sock Shop, 5 co-tenant CPU contention + 7 slow-datastore incidents. Every method sees the
same runs. Where the blueprint reads the raw kernel trace, the LLM arms are handed the
**identical measurements** (one shared evidence pack per run) so the comparison is about
method, not access.

## Headline

| Method | Component | Fully correct | Answered | Precision | Median time | Cost/incident |
|---|---|---|---|---|---|---|
| **Blueprint** (rules, no model) | 83% | **83%** | 83% | **100%** | 508 s | **$0** |
| Agent + kernel pack | **100%** | 58% | 100% | 100% | 128 s | $0.021 |
| Agent, no kernel pack | **100%** | 58% | 100% | 100% | 118 s | $0.014 |
| Statistical rule-tree | 42% | 42% | 100% | 42% | — | $0 |
| BARO (published) | 0% | n/a | 100% | 0% | — | $0 |

*Fully correct = right component **and** right fault type. BARO localizes only, so fault
typing is n/a rather than 0. Precision is scored over answers actually given.*

## The result that matters: nobody else is good at both faults

| Fully correct | Co-tenant (n=5) | Datastore (n=7) | Total |
|---|---|---|---|
| **Blueprint** | **5/5** | 5/7 | **10/12** |
| Agent | **0/5** | **7/7** | 7/12 |
| Statistical | **5/5** | 0/7 | 5/12 |
| BARO | 0/5 | 0/7 | 0/12 |

Each alternative is strong on one fault and blind on the other. The blueprint is the only
method above chance on both, and it wins the total.

The reason is mechanical, not luck. **The agent never once types co-tenant contention
correctly.** It localizes the culprit perfectly every time, then calls it `cpu_saturation`
or `cpu_throttling` — plausible labels that are both wrong. It has no rule that separates
"threads cannot get a CPU" from "one service is capped". The blueprint has exactly that
rule, measured: runqueue delay inflates while socket-waiting syscalls stay flat.

## Giving the model the kernel data changed nothing

This is the cleanest control in the study, and the answer is negative.

| | Component | Fully correct | Tokens |
|---|---|---|---|
| Agent **with** kernel measurements | 100% | 58% | 170,493 |
| Agent **without** them | 100% | 58% | 105,583 |

Identical component on **12/12**. Fault type differed on 2 incidents, and in both the pack
turned one wrong answer into a *different* wrong answer (`cpu_throttling` → `cpu_saturation`;
ground truth was neither).

Cost of supplying it: **+61% tokens for zero accuracy gain.**

So the blueprint's advantage is **not** privileged access to the kernel trace — the model
had the same numbers and did nothing with them. The advantage is the decision rule that
says which number settles the question.

## Abstention is not the same as being wrong

The blueprint answers 10 of 12 and is correct on all 10 — **100% precision**. Its two
non-answers are both *subtle*-intensity datastore runs:

| Intensity | datastore `poll` inflation |
|---|---|
| aggressive (5 runs) | **30.4 – 36.8×** |
| subtle (2 runs) | **4.43 – 4.52×** |

The threshold is 5×. The subtle runs land just under it, so the blueprint declines rather
than guessing — which is what its stopping conditions instruct.

**We did not lower the threshold to capture them.** Moving 5× → 4× would score 12/12 on this
test set and would be fitting to it; the co-tenant runs reach 2.99×, so the margin would
shrink from 10× to 1.5×. The honest claim is that the blueprint fires when the signal is
strong and declines when it is weak.

Compare BARO: it answers every incident and is right on none, predicting `carts` regardless
of the fault. A method that always answers is not more useful than one that knows when it
cannot.

## Where we lose: wall-clock time

The blueprint takes **508 s** per incident against the agent's **128 s**. Reading a raw
kernel trace is expensive — roughly 7–9 minutes of decoding per run.

Honest framing: the blueprint is **free** ($0 vs 2 cents) and **more accurate on fault
typing**, but it is **4× slower** today. The decode is also one-off and shared: all methods
in this study reused a single pack per run.

## What this does and does not show

**Shows** — on these two fault families, a measured decision rule beats a tool-using LLM on
fault typing (83% vs 58%), beats both published methods outright, never answers wrongly, and
costs nothing per incident.

**Does not show** — that this generalises. Twelve incidents on one application, two fault
types. One incident moves the total by 8 points. The agent's perfect localization suggests
these faults are easy to *locate*; the difficulty is in *naming* them, which is where the
blueprint earns its place.

**Also worth stating**: the two published baselines cannot consume kernel data at all. They
received identical incidents with identical metrics and traces, but the kernel layer is
unusable to them by construction — consistent with our earlier finding that adding kernel
features to the academic method changed nothing.

## Reproducing

```bash
bash /scratch/yuvraj17/extract_batch.sh          # stage L0 for all runs
bash /scratch/yuvraj17/build_packs.sh            # one shared evidence pack per run
bash /scratch/yuvraj17/run_comparison.sh         # every arm, same incidents
python blueprints/lib/compare_methods.py         # one scorer for all
```

Raw results: `/scratch/yuvraj17/comparison/comparison.json` (per-incident rows included).
