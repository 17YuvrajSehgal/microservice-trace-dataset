# How runs are judged (evidence-based, not score.py)

`score.py` graded by keyword-matching the verdict text. It mis-scored in both directions
(crediting "cpu" in a clean run's evidence; failing a correct noisy-neighbor because it named the
aggressor not a victim). We no longer use it for the final call. Instead each run is judged
against **(a) its `ground_truth.json`, (b) the injection recipe that actually caused the fault**
(`microservice-lttng-data-collection-scripts/faults/<name>.sh`), and **(c) the agent's committed
verdict** — read, not pattern-matched.

Integrity first: this is for a research paper. The rubric below is fixed *before* a combo is
judged. Every run's judgment records the agent's own words, the ground truth, and a one-line
reason, so any reviewer can re-check it. When in doubt, grade **down**. Never redefine a
criterion after seeing results to make a number look better.

## What each fault actually injects (the mechanism the agent must find)

| family | recipe does | kernel signature the agent should land on |
|---|---|---|
| svc_cpu_cap | `docker update --cpus=X` on one container (cgroup `cpu.max`) | that container's process waits runnable (throttled) while CPUs sit idle; flat per-period on-CPU ceiling |
| svc_mem_cap | `docker update -m M --memory-swap M` (hard, no swap) | memcg reclaim bursts in the victim; often an OOM kill / exit inside the limit |
| noisy_neighbor | a batch of CPU-hungry workers next to the services (**host scope**) | one process group holds most CPU; victims wait in short slices; machine goes busy, little idle |
| slow_db | delay injected on the service→DB network path (hundreds of ms) | request→answer gap stretches; for Go/Node victims the `read()` itself is 0 ms (non-blocking) |
| svc_net | `tc netem` delay+jitter+loss on one container's interface | retransmissions / throughput collapse on that flow; delay inferred when collapse >> loss |

## The three questions per run

1. **Mechanism** — did the agent commit to the *kind* of fault the recipe injected? (not a symptom
   like "activity collapse"; the actual mechanism.)
2. **Location** — did it name the right victim service, or a pid_ns that maps to the right
   container? For **host-scope** faults (noisy_neighbor) there is no single victim: naming the
   aggressor process, or "host-wide", is correct.
3. **Timing** — does the reported window overlap the injection window? Supporting evidence, not
   decisive on its own.

## Grades (per fault run)

- **DETECTED** — mechanism correct **and** location correct. The headline metric.
- **PARTIAL** — mechanism correct but location wrong/vague, or a strong, specific localization
  with an imprecise mechanism. Reported in its own column; **never counted as DETECTED.**
- **MISS** — wrong mechanism, or the agent said "normal"/"other"/"unknown" on a real fault.

For a **control** (fault-free `normal` run): **CORRECT** if the agent says normal / no injected
fault; **FALSE ALARM** otherwise.

### Conservative rules (bias against our own method)

- "other" / "unknown" / "normal" on a real fault → MISS, always.
- A symptom without the mechanism ("host-wide slowdown", "activity collapse") → MISS or at most
  PARTIAL, never DETECTED.
- A keyword appearing only in the evidence narration is not a detection — judge the **committed
  fault_type and root cause**, the conclusion the agent stands behind.
- Right mechanism but wrong container (e.g. the throttle found in the wrong one of Train Ticket's
  60 `ts-*` services) → PARTIAL, not DETECTED.
- Ties break to the lower grade, with the reason recorded.

## Record kept per run (auditable)

`Blueprint/eval/results/<dataset>/<problem>/JUDGMENTS.md` — one row per run:

`run_id | gt: <fault>/<target>/<window> | agent: <fault_type>/<where>/<when> | GRADE | reason`

Headline numbers quote DETECTED only; PARTIAL and MISS are shown beside them so the gap is
visible. Window IoU and tool-failure notes are kept as supporting columns, not as the grade.
