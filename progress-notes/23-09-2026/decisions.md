# 23 September 2026

## The 6000-char reply cap was deleting the answer, not trimming it

Went looking at `SENT_CAP = 6000` because it was flagged as maybe-too-small. It is worse than
too small. Measured across all 720 q2 transcripts, 11,189 tool calls:

| tool | calls | cut | median result | thrown away |
|---|---|---|---|---|
| `ctf_proclife` | 742 | **99.3%** | 41 KB | **86%** |
| `ctf_procdiff` | 1201 | 87.3% | 7.8 KB | 23% |
| `ctf_lines` | 3016 | 67.7% | 7.6 KB | 29% |

Two separate faults, both from the same line - `sent = full[:SENT_CAP]`, a slice of the JSON
**string**:

**1. Every cut result was unparseable.** All 3,827 of them, chopped mid-number or mid-string.
The model was being handed broken JSON and reasoning on it anyway.

**2. A prefix slice does not sample a result, it deletes late keys outright.** `json.dumps`
keeps insertion order. `ctf_proclife` returns two lists, and the second one never arrived:

| field | reached the model |
|---|---|
| `present_for_only_part_of_the_recording` | 99.3% |
| `present_throughout` | **4.7%** |
| `n_containers_seen` | **0%** |
| `how_to_read` | **0%** |

**Why this is the whole story.** An injected stress process SPAWNS, so it lands in the first
list. A CPU-capped or network-degraded container was already running, so it only lands in
`present_throughout` - the list the agent essentially never saw. WHERE splits exactly there,
on both applications:

| culprit | Sock Shop | Train Ticket |
|---|---|---|
| spawns (anomaly_cpu, noisy_neighbor) | 55/60, 40/60 | 54/60, 55/60 |
| already running (slow_db, svc_cpu_cap, svc_net) | 24/60, 1/60, 0/60 | 3/60, 0/60, 0/60 |

**The cap was buying nothing.** Peak context use is 26.6k tokens at the median run and 48.7k at
the maximum - 6.6% of the model's 400k window. We were destroying evidence to save room that
was never in use.

### The fix

`_fit_result()` trims by dropping whole ROWS from the longest lists, then grows them back to
fill the budget, and writes a `_truncated` block naming what it dropped so the model can tell a
subset from a complete answer and re-query. Per-tool budgets sized to carry each tool's median
result whole (`ctf_proclife` 45 KB, `ctf_procdiff` 24 KB, `ctf_lines` 18 KB, default 12 KB).

Replayed over the real results. At the new budgets nothing is cut at all. Held to the OLD
6000-char budget, so the comparison is like for like:

| | old slice | new fitter |
|---|---|---|
| unparseable output | 100% of cut results | 0 |
| `present_throughout` delivered | 8.7% | 99.0% |
| `how_to_read` delivered | 0% | 99.0% |

**This invalidates the 720 runs for comparison against anything run after it.** That is the
right trade - the old number is a measurement of a harness bug - but it means the q2-ss/q2-tt
results are now "agent v1" and must be labelled that way, not silently compared against.

**Lesson worth keeping: the tool results were always correct.** Everything above was already
sitting in the transcripts. The agent was never the bottleneck we thought it was; the pipe to
it was. Before adding capability to an agent, check what it is actually receiving.
