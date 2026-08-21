# Review-response experiments (answers.md items 1, 3, 8)

23 incidents (12 Sock Shop + 11 Train Ticket), one per fault family, masked, leakage-audited.
**115/115 transcripts PASS the auditor (0 hard leaks, 0 soft warnings).** Total cost $1.29.

Driver: `review_driver.sh` → `results/review/`. Every step gets its OWN transcripts dir: all
steps use `grid=full`, so they share the transcript filename `<app>/<run>/full.json` and a
shared directory silently overwrites earlier steps (this happened on the first attempt and
cost 69 of 92 audit records — the numbers survived, the audit trail did not).

---

## Item 3 — does the agent loop add anything over a single shot?

| setup | component | fully correct | tool calls | tokens/incident |
|---|---|---|---|---|
| Agent: 7 tools + briefing (frozen config) | 78% | 52% | 8.3 | 10,605 |
| Agent: same + ranked answers | 74% | 48% | 9.3 | 12,354 |
| **No tools: briefing only, one shot** | **78%** | **52%** | 0 | 2,869 |
| **No tools: raw survey dump, one shot** | **83%** | **57%** | 0 | 5,892 |

**The briefing-only control ties the full agent exactly — 78%/52% either way — using 27% of
the tokens and zero tool calls.** The cruder raw-dump control is a fault ahead of both.

The control is not a strawman: it receives the same deterministic evidence briefing the agent
gets (same masking), built by plain code that surveys every tool. So the finding is not "the
model needs no telemetry"; it is:

> **The work is done by the deterministic evidence construction, not by the agentic loop.**
> Eight to ten rounds of interactive querying rediscover what one good survey already contains.

Caveats, stated plainly:
- n=23, so **one fault is worth ~4.3 points**. "Indistinguishable" is the defensible claim;
  "no-tools wins" is not.
- This same frozen configuration scores **87%/57%** in the main campaign and **78%/52%** here.
  That 9-point swing on identical settings is the measured noise band showing up in the
  headline itself, and is the strongest argument yet that quoted figures need repeats.
- The tool loop may still matter for faults or systems outside this set; what is shown is that
  on *these* 23 it buys nothing measurable.

## Item 8 — ranked answers (up to 5 evidence-backed candidates)

Candidates are **evidence-ranked**: an alternative without its own supporting evidence is
dropped by the harness, so the list is not merely the model's next-likeliest tokens.

| setup | axis | hit@1 | hit@3 | hit@5 | MRR | MAP |
|---|---|---|---|---|---|---|
| Agent (tools) | component | 74% | 87% | 87% | 0.80 | 0.80 |
| Agent (tools) | fault type | 52% | 65% | 65% | 0.59 | 0.59 |
| Agent (tools) | both | 48% | 61% | 61% | 0.54 | 0.54 |
| No tools (briefing) | component | 83% | 96% | 96% | 0.89 | 0.89 |
| No tools (briefing) | fault type | 57% | 65% | 65% | 0.61 | 0.61 |
| No tools (briefing) | both | 57% | 65% | 65% | 0.61 | 0.61 |

- Allowing three guesses lifts fault typing **52% → 65%** and localization **74% → 87%**,
  which is the predicted effect: most "wrong type" answers are near-misses at label boundaries.
- The model volunteers only **2.0–2.6 candidates** despite being allowed 5 — the evidence
  filter is doing its job rather than the model padding the list to the cap.
- hit@3 == hit@5 everywhere: nothing is ever recovered by the 4th or 5th guess.
- Directly comparable to the ranked non-LLM baselines (AC@1 46%, AC@3 63%, MRR 0.54).

## Item 1 — component census

Grounded on each run's own `meta/` container roster (`tools.services()` also surfaces metric
labels that are not containers — os version strings, scrape-job names — which inflated a first
draft to 17/50 components).

| | components | emit request spans | span-less |
|---|---|---|---|
| Sock Shop | 16 | 6 | 10 |
| Train Ticket | 46 | 36 | 10 |

**Every datastore in both applications is span-less** (0/4 and 0/3) while the kernel layer sees
4/4 and 2/3. That is the blind-spot premise of the dataset, measured rather than asserted.
Span-less components are databases, brokers, caches, registries, proxies and the injected fault
containers. Full table: `results/review/component_census.json`.

## Not run

- **Item 6** (forced-guide cross matrix, ~$5) — held: it measures how well guides steer the
  agent, which matters less if the agent loop is not the contribution.
- **Items 7, 9** (code-level mutations, multi-fault runs) — need the collection VM, which is off.
