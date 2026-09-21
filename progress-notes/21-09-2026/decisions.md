# 21-09-2026 — decisions

## 1. The agent must find the incident itself. Everything else follows from this.

Yuvraj, on what the experiment is actually for:

> "in a real life when a engineer is given a trace - they don't know when and what kind of
> anomaly was present in the system - they have to do this analysis on there own - the agent
> should do the same"

This caught a flaw that ran deeper than the tool I had just written.

### What was leaking

I built `query_ctf` with `window="incident"`, resolved from `ground_truth.json`'s
`injection_start_utc`. That hands over the answer to *when*. Removed — and `ctf_tool.py` now
carries a rule at the top: **nothing in it may read ground truth.**

**The L0 evidence pack has the same flaw, and worse.** Every figure in it is "baseline window
vs incident window", and both windows come from the injection timestamps:

```
"what": "on-CPU time per process, baseline window vs incident window"
host_util_baseline 0.4817   host_util_incident 0.6751
```

That does not merely leak *when*. It pre-frames the entire analysis around the correct window,
so an agent holding it is **describing an anomaly somebody already isolated**, not finding one.
The experiment could not have supported the claim we want to make.

### Decision: drop the pack (option 1 of 3)

The alternatives were to rebuild the pack without ground-truth windows (~745 s per run to
regenerate) or to narrow the claim to "given the window, does the blueprint help interpret it".
Yuvraj chose to drop it.

**Consequence, stated up front so it is not a surprise:** scores will fall in *both* arms,
probably a lot. That is fine. The comparison is what carries the result, and if blueprints help
anywhere they should help most when the agent is genuinely lost.

## 2. The tools that replace it

The engineer's workflow, not a pre-computed answer:

| tool | purpose |
|---|---|
| `ctf_timespan` | recording start/end, read from the trace. The only free orientation. |
| `ctf_timeline` | one event counted across the WHOLE trace, bucketed, with a bar chart — **the change-point finder** |
| `query_ctf` | counts, rate/s, top processes and real event lines over a range **the agent picks** |

`ctf_timeline` warns the agent to confirm any candidate step against a second unrelated event,
because a step in *everything* means the workload changed rather than the system misbehaving.

Bounded hard, because one incident is ~20 million events and a full decode costs ~745 s: event
pattern always required, raw lines capped at 40, scan caps on every call. A truncated read says
so explicitly and labels its counts a **lower bound** — a silent partial answer is worse than an
error, because the agent would treat it as a count.

## 3. Steps raised 14 → 60

14 was tuned for seven pre-aggregated tools and a pack that pre-located the incident. The agent
now starts with neither. A run that hits the cap mid-investigation scores as a failure of the
agent when it was a failure of the budget. 60 is deliberately generous for the pilot — measure
what is actually used, then tighten.

## 4. Three bugs the single-cell pilot caught

Running one cell before the 60 paid for itself immediately:

| bug | evidence | fix |
|---|---|---|
| agent saw **no data** | `list_services` returned only `host`; it answered, correctly, "the incident telemetry contains no traces, topology, logs, metrics, or kernel data" | bundles are L0 only — now superseded by the tools-only design above |
| `tokens` always 0 | `diagnose` returns `{"in":…, "out":…}`, not `in_tokens`/`out_tokens` | read the right keys |
| **narrowing metrics incoherent** | `both_ok=False` but `rank=1`, `set_f1=1.0`, `mrr=1.0` | `rank` now means *position of the correct answer*, matched against ground truth |

The third would have quietly ruined the results: every wrong answer would have scored a perfect
narrowing. Catching it is the entire argument for running one cell before sixty.

## 5. Also settled today

- **Model**: `gpt-5.4-mini` (azure). Cheapest is nano, but full `gpt-5.4` scored 0/6 on
  `noisy_neighbor` unaided — with nano there is a real risk both arms floor at 0% and the pilot
  teaches nothing. **Nano numbers must never be tabled next to the 2 Sept baseline of 56%**,
  which ran on full `gpt-5.4`.
- **Egress**: compute nodes are firewalled (DNS resolves, every TCP 443 blocked, no proxy).
  Login nodes reach the APIs (HTTP 401 = reachable). So the runs go on the login node — light
  work, waiting on API calls rather than saturating I/O, unlike the decompression that earned a
  telling-off on 18 Sept.
- **Skills were never generated on Trillium** — `skills-generated/` was empty, so the first run
  failed to find its blueprint. Generated all 11 from the blueprints.
- `RCA_SEND_TEMPERATURE=0` is **correct and must stay**: it is a flag meaning "do not send
  temperature", not a temperature of zero. The model default is stochastic, which is what the
  5 repeats measure. I initially misread this and nearly had it changed.

## Open

- **The diagnosis schema has no field for WHEN.** If the agent must report the incident window,
  it needs one, or we cannot score whether it found the right one. Next decision.
- `ranked` came back empty on the pilot, so `rank_k=5` reaching the schema is still unverified.
- Pack coverage per app was never mapped; now moot for the pilot, still relevant if the packs
  are used for anything else.

## 6. The first tools-only run, and the three bugs it found

One cell, `noisy_neighbor / given / hint`. 98.5 s, 21 tool calls, 77,981 tokens.

| what | agent said | truth |
|---|---|---|
| service | `host` | `host` — right |
| fault | `normal` | `noisy_neighbor` — wrong |
| window | 09:10:55.186 – 09:10:58.851 | 13:11:54Z – 13:13:55Z — IoU 0.0 |

The agent was not being careless. Every one of those answers follows correctly from what my
tools told it. All three bugs were mine, written the same day.

### Clock — the trace said 09:10, the run happened at 13:11

babeltrace2 renders timestamps in the **reader's local time** unless told otherwise. Trillium
is EDT, so every trace read four hours early. Nothing else in a bundle works that way —
`ground_truth.json`, the meta snapshots and the load log are all UTC. So `window_iou` could
never have scored above zero, even if the agent had found the exact right moment. `--clock-gmt`
now goes on every babeltrace call.

This one is worth remembering because it is invisible: a timestamp that is wrong by a constant
offset looks perfectly reasonable on its own.

### Span — a partial read reported as the whole recording

`ctf_timespan` decoded the trace to find its first and last event, hit its own 4-million-event
cap, and returned what it had read **as if that were the entire trace**: 3.6 seconds of a
219-second recording. The agent then said, reasonably, "ctf_timespan shows the full trace is
only 09:10:55–09:10:58" and searched inside those 3.6 seconds.

Now read from the bundle's `meta/` cgroup tick snapshots, which are stamped
`_tick_YYYYMMDDTHHMMSSZ` and bound when the recorder ran. That is collection metadata any
engineer would have on a real trace. It is **not** `ground_truth.json`, which nothing in
`ctf_tool.py` may read — the rule at the top of that file still holds.

### Coverage — a chart drawn from a scan that stopped early

`ctf_timeline` drew a full-width bar chart from a capped scan, so "no clearly isolated step"
could equally mean "I never looked at most of it". It now states the range it actually covered
and tells the agent to check that against `ctf_timespan`.

## 7. Phase 1 is kernel traces only

Yuvraj: *"right now our first phase of experiments is restricted to kernel traces only - no
logs/metrics/traces etc."*

The seven other query tools read derived frames that L0 bundles do not carry. Offering them
was worse than wasting calls — **the agent read their emptiness as evidence of health**. From
the pilot transcript, its reason for answering `normal`:

> query_metrics returned no metrics, query_kernel is unavailable, and there are no service
> spans/logs/topology edges

Every clause is true and none of it is evidence about the system. So `KERNEL_ONLY_TOOLS` now
offers `ctf_timespan`, `ctf_timeline`, `query_ctf`, `submit_diagnosis` and nothing else, and
the prompt says plainly that the kernel trace **is** the dataset rather than a gap in it.

Absence of a tool's output is not absence of a fault. Worth stating in the paper, since any
modality-ablation study can make the same mistake.

## 8. Closed from §5

- The diagnosis schema now has a WHEN field. `submit_diagnosis` requires `incident_window` and
  `window_evidence`, and `score_window()` grades it by overlap with the true injection window —
  recall, precision, IoU. `unknown` counts as an honest abstention, not a wrong answer, because
  the schema tells the agent an invented window is worse than an admitted gap and the metric
  has to agree with the instruction.
