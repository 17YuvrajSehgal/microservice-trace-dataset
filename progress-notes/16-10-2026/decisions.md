# 16-10-2026 — decisions

(The first half of today's work — Blueprint/ workspace, agent copy + trim,
blueprint tool wiring, OpenRouter check — is logged at the end of
`../15-10-2026/decisions.md` under "(16-10)" headers; this file continues
from there.)

## First blueprint-guided agent run: correct verdict, blueprint tools unused

`agent_v2` + svc_cpu_cap blueprint on `t3_implement_cap25_r1`
(gpt-6-luna via OpenRouter, 560 s, 1.41M in / 25.5k out tokens):

- **Verdict correct and precise**: `python3 in pid_ns 4026531836`,
  `cpu_throttling`, "~25 ms per 100 ms = 0.20–0.24 cores" (true cap 0.25),
  window = the python3 phase, confidence 0.68 with honest caveats.
- To make the index tools work locally, built the ctf count index FROM the
  decoded trace.txt.gz (byte-compatible with build_ctf_index.py; 0.7 s,
  157 KB) -> `Blueprint/agent/ctf-index/`. Also fixed ctf_timespan to
  auto-discover the trace layout (trace/kernel vs kernel/kernel).
- **Headline workflow finding: 0 of 69 tool calls used blueprint_tool.**
  run_python 28, ctf_timeline 23, ctf_lines 6, timespan 5, proclife 4,
  query_ctf 3. The planner's subtasks mirrored the blueprint's METHOD, but
  workers executed it with generic tools + self-written pandas. Blueprint
  worked as knowledge, not as toolkit. The reviewer even flagged the gap
  sched_budget.py would have filled (runnable-wait comparison).
- Full step-by-step logs for the user's analysis:
  `Blueprint/agent/transcripts/v2/t3_implement_cap25_r1.json` (+console.log).

## Blueprint-only mode added (user ask: test the blueprint toolkit alone)

`diagnose(..., blueprint_only=True)` / `--blueprint-only`: toolset becomes
[blueprint_tool, note_finding] — no index tools, no run_python. Design:

- **Own prompt head** (_BP_HEAD/_BP_WORKER/_BP_SYNTH): the stock prompts
  describe seven tools and DEMAND run_python subtasks; v2's history shows
  the model believes the prompt over the schema, so advertising tools that
  are not offered would poison the test.
- **Planner skipped** (fixed single subtask, no API call): a blueprint is a
  sequential procedure; parallel subtasks would each need the previous
  step's output. One investigator walks the steps in order.
- Index tools stay in the codebase untouched — this is a per-run mode, so
  flipping back is just dropping the flag. The comparison (same run, same
  model): full-toolkit transcript vs `.bponly.json` transcript.

Launched on the same run -> `transcripts/v2/t3_implement_cap25_r1.bponly.*`.

## A/B result: blueprint tools WORK, blueprint-only is NOT sufficient

Same run, same model, side by side:

| | full toolkit | blueprint-only |
|---|---|---|
| verdict | cpu_throttling, python3 in pid_ns, 0.20-0.24 cores | cpu_saturation, "host", cap "unconfirmed" |
| correct? | YES (true: 0.25-core cgroup cap) | NO (right evidence, wrong attribution) |
| confidence | 0.68 | 0.57 |
| tool calls | 69 (0 blueprint) | 31 (ALL blueprint: budget 9, slice 7, rhythm 5, idx 5, wake 4, victim 1; 0 errors) |
| tokens | 1.41M in / 25.5k out | 0.50M in / 16.7k out |
| wall | 560 s | 569 s |

The toolkit itself executed flawlessly (31/31 calls clean, incl. the NTFS
colon fix). The miss is in the BLUEPRINT'S DECISION RULES on this workload:

1. **Two victims = "host overload" misfire.** The cap covers the agent's
   whole cgroup, so TWO processes (8192 python3 + 8126) showed long waits;
   the blueprint's Step-4 rule "many processes suffer -> whole machine short
   of CPU" pushed the agent to `host`. The blueprint assumes a cap hits ONE
   process; a cgroup cap hits a process TREE.
2. **Bursty victim breaks the rhythm check.** rhythm.py scores 0.29-0.40
   (threshold 0.5): the agent workload idles between LLM calls, so the
   quota beat is weak in wall-clock buckets — exactly the whole-run-
   averaging gap flagged in EVALUATION-on-agentic-runs.md.
3. **No baseline window** (the cap spans the whole trace) — Step 4 wants a
   normal stretch; the agent correctly noted it had none and lost
   confidence.

What the full-toolkit run had that decided it: run_python over
sched_stat_runtime (the index value_sum) computed the 25 ms/100 ms runtime
CEILING — the quantitative quota signature the blueprint only
approximates via `run` + rhythm.

DECISION: keep the index tools (the ceiling computation is the decisive
discriminator). Blueprint v2 should gain (a) a group-the-victims rule
(same cgroup/parent -> one capped group, not host overload) and (b) a
per-period on-CPU ceiling script (the blueprint's own Step-6 "Proposed"
item — this A/B is the evidence it is needed).

## Both blueprint fixes implemented (evidence-first)

(b) **cpu_ceiling.py** — ninth blueprint tool: the victim's on-CPU ms per
period from sched_switch; a flat ceiling below the period = the quota.
VALIDATED before writing the text, on runs with known limits:
- cap25: median/p90 25.0 ms, max 25.1, 82% flat -> 0.25 cores (true 0.25)
- cap50: 50.1 ms, 87% flat -> 0.50 cores (true 0.5)
- nocap: pegs at the full 100 ms -> correctly reads "no cap" (and the tool
  says a full-period ceiling on one thread cannot be told from a 1-core
  cap — honest ambiguity, stated in its output and in the blueprint).

(a) **Group-the-victims rule** in the text: §1.3 cap row ("one container =
possibly SEVERAL processes; a cgroup limit covers the tree"), overload row
(requires sufferers in DIFFERENT containers + no idle CPUs), and Step 4's
"many processes suffer" bullet now routes through victim_info namespaces +
wake_graph parentage: same container -> ONE victim group, continue.

Blueprint text integration: Step 6 retitled "...then measure the ceiling";
"no beat" no longer stops (bursty victims show weak beats — exactly what
sank the bp-only run) but falls through to 6b; Step 8 estimates from the
ceiling and warns that whole-slice run averages dilute for bursty victims;
Part 5 limits updated (rhythm thresholds one-case, ceiling three-run
validated); counts 8->9 everywhere. agent blueprint_tool picks the new
script up automatically (dynamic dir listing - verified).

## Re-run with blueprint v2: the bp-only arm now gets it RIGHT

Three arms, same run (t3_implement_cap25_r1), same model:

| | full toolkit | bp-only, blueprint v1 | bp-only, blueprint v2 |
|---|---|---|---|
| verdict | cpu_throttling, python3 pid_ns, 0.20-0.24 cores | cpu_saturation "host" | **cpu_throttling, python3 PID 8192 in pid_ns, 0.25 cores** |
| correct | yes | NO | **yes** |
| confidence | 0.68 | 0.57 | 0.58 |
| tool calls | 69 | 31 | 38 (1 error) |
| tokens in/out | 1.41M / 25.5k | 0.50M / 16.7k | **0.49M / 13.0k** |
| wall | 560 s | 569 s | **375 s** |

The agent ran cpu_ceiling.py 4x and quoted it verbatim in the verdict
("25.0 ms per 100 ms, 79% flat -> ~0.25-core cap"); the grouping rule kept
PID 8126's parallel waits from flipping it to "host". Honest hedging
remains ("suggestive, not confirmed: no cgroup throttle counters in a
kernel trace") - correct epistemics for kernel-only evidence.

HEADLINE: the blueprint + its own nine scripts now matches the full
index-toolkit verdict at ~1/3 the input tokens and 2/3 the wall time. And
the loop that got here is itself the result: blueprint -> agent run ->
failure analysis -> two targeted fixes -> correct verdict. Transcripts:
.json (full), .bponly.json (v1, wrong), .bponly2.json (v2, right).

## bp-only v2 on cap50 + nocap: 1 clean pass, 1 honest miss (tool bug found)

| run | truth | verdict | calls / tokens / wall |
|---|---|---|---|
| nocap | no fault | **normal, conf 0.91 — clean rejection** | 6 / 139k / 70 s |
| cap50 | 0.5-core cap | "other / unknown", conf 0.63 — found both waiters, refused to commit | 67 / 633k / 431 s |

**nocap is the blueprint working exactly as written**: Step-3 budgets found
no waits >=10 ms, the Step-4 stop rule fired, 6 tool calls total, honest
scope note ("this blueprint does not test other fault classes"). The
false-positive check passes.

**cap50 missed for two diagnosable reasons** (from the transcript):
1. **victim_info.py bug poisoned the grouping rule.** For python3
   (8969/8965) it printed `cgroup_ns=0, ipc_ns=0, net_ns=0` (fields it
   could not read from that slice) vs real host values for claude (8903).
   The model read "victim namespaces differ from host" -> "a separate
   container" -> grouping blocked -> "cannot establish a single capped
   service". In truth all these processes share every namespace (the cap
   is pure cgroup; no containers in these runs) — and pid_ns actually
   MATCHED in the output. A 0 that means "unknown" must not look like a
   namespace value.
2. **cpu_ceiling.py was never run** (0 of 67 calls). The worker burned its
   budget on 26 extract_slice + 26 sched_budget sweeps and never reached
   Step 6b, despite the blueprint sampling guidance (~6 slices). The
   decisive quota measurement (50.1 ms/100 ms, validated by hand on this
   exact run) was one call away.

Note the failure MODE is good: not a confident wrong answer (v1's "host")
but an honest "unconfirmed" — the fixed blueprint degrades gracefully.

Proposed next fixes (not yet applied): (a) victim_info.py prints
"unknown" instead of 0 and compares only fields it actually read;
(b) blueprint Step 3 caps the slice sweep and tells the investigator to
run cpu_ceiling.py on the FIRST suspect rather than after exhaustive
sampling. Scorecard so far (bp-only v2): cap25 PASS, cap50 MISS(honest),
nocap PASS.

## Fixes applied; cap50 re-run -> CORRECT. Scorecard now 3/3

- victim_info.py: ns=0 means "tracer could not resolve", never a real
  namespace -> zeros dropped, values merged across events, verdict names
  the fields compared. Verified on the failed run's own slices: python3
  8969 now identical to the host on all five fields (was 3 zeros ->
  "separate container").
- README_v1: Step 3 discipline (6-8 slices, stop at first clear victim) +
  Step 6b "run the ceiling as soon as you have a victim; one call,
  decisive, do not postpone".

cap50 re-run (bponly3): **cpu_throttling, python3 PID 8969, "~50 ms per
100 ms = 0.5 CPU"** (true 0.5), conf 0.69, window 03:20:05-20:20. The
discipline change is visible in the numbers: extract_slice 26->8,
sched_budget 26->10, cpu_ceiling 0->4 (50.1 ms, 90% flat, quoted in the
verdict), 431->270 s, 633k->512k tokens. Honest hedge retained (no cgroup
counters in a kernel trace; 8903 also waits).

**Blueprint-only scorecard, blueprint v2.1: cap25 PASS, cap50 PASS,
nocap PASS (clean rejection).** Three agent-run iterations turned the
blueprint from 0/1 (v1: confident wrong "host") into 3/3 with a toolkit
that needs no index and ~1/3 the tokens of the full agent. The transcript
chain (.bponly -> .bponly2 -> .bponly3) is the audit record of the loop.

## Blueprint 2 chosen and built: noisy_neighbor

WHY noisy_neighbor (over svc_mem_cap, slow_db, svc_net): it is blueprint
1's nearest look-alike and that table row was marked "not tested"; the two
blueprints form a DISCRIMINATION PAIR; max tool reuse (one new script);
and local evaluation data exists now (t4_parallel runs = controlled
contention with exact ground truth). svc_mem_cap is the planned third.

Built evidence-first, same folder shape (README_v1 + tools/, no
agentic-os-noise inside):
- NEW TOOL cpu_hogs.py: who used the CPU in the slice, and who held it
  WHILE the victim waited. One pass, three-way verdict: neighbor
  (aggressor dominates, idle small) / cap (idle dominates) / overload
  (many names, idle small). Measured before writing:
  t4 W=16 -> ttworker 96% + idle 1% while claude waited; cap25 -> idle
  96%; nocap -> negligible waiting.
- Supporting worked-case numbers: workers run 0.17-0.18 / wait 0.49
  ((W-C)/W = 0.75 check), 320+ waits >=1ms each, max 14 ms (no 50 ms
  freezes - the wait-SHAPE separates neighbor from cap); rhythm 0.28 no
  beat; ceiling 14% flatness (vs 82-90% on real caps).
- README_v1 mirrors blueprint 1's structure; Step 6 (cpu_hogs on the
  victim) is the decisive check; Step 7 rules the cap OUT with rhythm +
  ceiling; look-alike tables of the two blueprints now point at each
  other in both directions.

2x2 DISCRIMINATION MATRIX launched (blueprint-only agent, gpt-6-luna):
neighbor-bp on {t4_w16, cap25, nocap} + cap-bp on t4_w16. Expected:
competition-from-ttworker / hand-to-cap / no-competition / starved-but-
no-quota. Transcripts tagged .nn1 / .cap1.
