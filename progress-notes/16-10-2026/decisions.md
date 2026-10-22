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

## Matrix round 1: 3/4. The miss discovered FAIR-SHARE MIMICRY

- NN-bp on cap25: PASS — "CPUs idle during waits -> throttling, not a
  neighbor" conf 0.92. The hand-over works.
- NN-bp on nocap: PASS — normal, conf 0.96.
- CAP-bp on t4_w16: PASS — rejected (no 50 ms freezes).
- NN-bp on t4_w16 (its own fault): MISS — called it a cap: "92% flatness
  at 27 ms/100 ms for PID 4500".

The miss is a real discrimination discovery: **N equal busy threads on C
cores each settle at a flat ~C/N of a core — fair sharing mimics a quota
ceiling.** Compounded by: the agent picked a ttworker as victim (the
aggressor group tops the wait table because it competes with itself), and
its baseline slice overlapped the 3.8 s worker phase. The separator is
the IDLE SHARE: cap -> 96% idle during waits; fair share -> 1%.

Fixes (both blueprints, commit "fair-share mimicry..."): NN Step 3
self-contention rule + Step 5 baseline check + Step 7 caveat; CAP gets
cpu_hogs.py as tenth tool (its Step-7 "proposed" checks now real),
Step 6b busy-CPUs caveat, Step 5 routing to the NN blueprint. The pair
now routes to each other in both directions.

## Matrix round 2 (fixed blueprints): ALL CELLS PASS

| cell | verdict |
|---|---|
| NN-bp on t4_w16 | **noisy_neighbor, ttworker (PIDs 4498-4513)**, conf 0.62; victim claude; "78% to the group, 10% idle"; honest hedge that onset is not shown (the phase nearly fills the trace) |
| CAP-bp on t4_w16 | other/unknown, conf 0.98 — refuses the cap |

Full scorecard over both blueprints, blueprint-only agent: cap-bp 3/3
(cap25, cap50, nocap) + reject-contention; nn-bp 3/3 (t4_w16, cap25,
nocap). SIX distinct verdict cells, all correct, each wrong-fault cell
refused with the right reason. Next validation stage: unseen data — the
8+8 StrataTrace noisy_neighbor and svc_cpu_cap runs on Trillium.

## UNSEEN-DATA 2x2 on Trillium (StrataTrace v2 Sock Shop)

Setup: agent local, blueprint_tool runs ON TRILLIUM over ssh (blueprints
Runner remote mode, commit b02ac31: run_dir "trillium:/path", tools at
/scratch/.../bp_eval/<blueprint>/, babeltrace2->bt21.sh shim; wsl -e to
stop WSL's shell expanding $PATH locally). Runs chosen to be truly unseen:
svc_cpu_cap_aggressive_steady_r3 (r1 is the blueprint's original worked
case) and noisy_neighbor_aggressive_steady_r2. 12 CPUs, ~245 s traces,
java/stress-ng — different app, scale, and injection from the agentic
runs the blueprints were iterated on.

| cell | verdict | vs truth |
|---|---|---|
| cap-bp on cap r3 | "other", java in pid_ns, conf 0.82 — starvation measured exactly (run 0.63->0.19, 747-824 waits>=50ms, CPUs idle) but "ceiling not flat" withheld the label | near-miss, honest |
| nn-bp on cap r3 | **cpu_throttling, java in pid_ns, conf 0.90** — "100 ms cadence, 20-26 ms per 100 ms while CPUs idle" (true cap 0.2 cores) | CORRECT via routing |
| nn-bp on neighbor r2 | "host/cpu_saturation" 0.76 — FOUND stress-ng-cpu (new, 4 procs, 17%) but the dominance rule (calibrated at 96% local) refused it at 18%-while-waiting | near-miss, honest |
| cap-bp on neighbor r2 | **noisy_neighbor, stress-ng-cpu in pid_ns 4026533601, conf 0.76** — named the injected aggressor container | CORRECT via routing |

Both unseen runs were diagnosed correctly by the PAIR: each blueprint's
routing-out rules solved the other's fault, while each was over-cautious
confirming its own. 2/4 exact + 2/4 honest hedges, ZERO confident-wrong.

Gaps for the next iteration (not yet applied):
1. nn-bp neighbor criterion: dominance (96%, from 4x local oversub) is too
   strict for subtle real neighbors (thief_share sized so KPIs barely
   move). Use ARRIVAL+CORRELATION: a NEW named group whose appearance
   coincides with the wait rise is the aggressor even at modest share;
   dominance only separates neighbor from overload when nothing new came.
2. cap-bp ceiling flatness: cell 1 read "not flat" where cell 4 read a
   clean 20-26 ms cadence — slice choice sensitivity on wavy load; the
   ceiling should be read on the victim's BUSY stretch (the blueprint
   says this for run-average but 6b needs the same note).

## Blueprint 3 chosen and built: slow_db (branch 3-slow-db)

WHY slow_db as #3 (user's pick, branch name): biggest family (11+11), TT
side is no_metric_signature so the kernel trace is the differentiator, and
it opens the SLEEPING-victim class (deps/locks) after two CPU blueprints.

Built evidence-first on slow_db_aggressive_steady_r1 (dev run; r2-r5,
burst, subtle, and all TT held out as unseen). Ground truth: toxiproxy
+500ms +-100 jitter downstream on catalogue-db, 14:38:01-14:40:01.

THE DESIGN DISCOVERY (changed the tool mid-build): blocking-read durations
measure NOTHING on async runtimes. Go/Node use non-blocking sockets +
epoll: read() returns instantly; measured the victim's reads at 0.0 ms
while every request took 500 ms. So sock_lag.py measures the
REQUEST-TO-ANSWER GAP instead: completed write -> next completed read
with data (ret>0), per fd. Works for both threaded and async runtimes.

Three new tools (13 total in 3_slow_db/tools):
- dep_slice.sh: slice keeping sched + blocking syscalls (fd + ret fields).
- sleep_where.py: S-time split by enclosing syscall (sock_read/event_loop/
  locks/send/timer/D). Honest finding: totals mislead (idle connection
  handlers park in reads; mongo conn threads dominate) - kept as the
  locks-vs-dependency discriminator, not the victim finder.
- sock_lag.py: the decisive tool. Census mode (all pids) finds the victim;
  per-fd mode pins the connection pool and the delay.

Validated numbers (all in README Appendix B): catalogue pool (6 fds) p50
0.9ms -> 503-543ms, p90 580-620 (injected 500+-100); chain inflation
load-gen 50->591ms, traefik 114->367ms; mysqld HEALTHY in fault (run 0.06,
0 waits, D 0, 99.9 threads parked) -> "delay in the PATH" - matches the
toxiproxy ground truth. Monitoring long-pollers (~5s gaps in BOTH slices)
documented as the ignore-against-baseline rule.

StrataTrace v2 profile check that enabled all this: the `*` syscall rule
IS in the traces (1,490 syscall event classes) - blueprint Step 1 makes
syscall presence a hard requirement with a stop rule.

4-cell rigorous matrix launched (bp-only, remote tools on Trillium):
sdb-bp on slow_db_r1 / normal_none_steady_r1 / svc_cpu_cap_r3 (cross) +
cap-bp on slow_db_r1 (cross). Tags .sdb1/.sdb1x/.capx.

## Both unseen-data fixes applied (commit a224c59)

1. Neighbor criterion is now two-form: HEAVY (dominates while-wait time,
   idle small) or SUBTLE (the group is NEW - absent in baseline - its
   arrival coincides with the wait rise, idle not the biggest share; even
   at 15-25%). Overload additionally requires nothing new arrived.
   "Arrival beats share" added to Part 5. cpu_hogs.py printed guidance
   updated in BOTH blueprints' copies.
2. Cap Step 6b: "low flatness? check your slice" - re-cut on the victim's
   busiest stretch before concluding (measured: same fault read "not
   flat" in one slice, clean 20-26 ms/100 ms in another).

Trillium copies re-pushed and verified (grep for the new guidance). Ready
to re-run the two near-miss cells / sweep the remaining unseen reps.

## Blueprint 4_svc_mem_cap built (evidence-first, branch 3-svc-mem-cap)

Folder named 4_ (user's name; avoids clashing with the 3_memory_cap
experiment dir). Eleven tools: the ten + NEW mem_pressure.py, plus
extract_slice.sh gains an optional events_regex arg (agent fallback in
blueprints.py extended to match).

Everything measured on local t6/t7 runs BEFORE writing the text:

- **The memcg discriminator**: mm_vmscan_memcg_reclaim_* = the CONTAINER's
  limit; direct reclaim/kswapd = HOST pressure. Soft-cap run: 9,224 memcg
  reclaims by ttmem in 32 s; baseline: zero; host events: zero.
- **Re-read ratio**: squeezed read 5,369 MB for a 1 GB working set (5+
  passes); baseline 1,074 MB (one pass). Job 32.4 s vs 8.5 s.
- **Kill-vs-finish gap** (the hard-limit detector): a killed process exits
  INSIDE its final reclaim - gap 0.02-0.37 ms on 3 known kills; finished
  processes exit 7.9-48.3 ms after (5 known finishes, two conditions).
  1 ms threshold, 20x margin. Earlier candidate rules REJECTED by data:
  "died near reclaim" false-fired on normal soft-cap completion;
  parent-died-with-it failed because a killed child's wrapper also exits.
- **Honest caveat measured**: victim D-share 0.87 (squeezed) vs 0.66 (cold
  baseline) - a memory-cap victim LOOKS like a slow-disk victim; D
  supports, reclaim+ratio prove.
- Tool bugs fixed during validation: sched_process_exit fires PER THREAD
  (now tid==pid only); rwbs is numeric (read=bit 4, write=bit 0,
  determined empirically).

Next: 5-cell agent matrix (soft/hard/healthy positives + both cross-
rejections vs the CPU blueprint).

## Anti-leak pass on both blueprints (user rule, now standing)

RULE: blueprints must carry NO evaluation-derived names or numbers -
the agent reads the blueprint during evaluation, so "stress-ng took 17%"
or "idle was 96%" is an answer key, not a lesson. Same principle as
skillreg's forbidden-token lint (stress-ng is literally on that list).

Applied (commit ef6d0c8): every "Measured: X%" in the steps is now
qualitative; the subtle-neighbor share band removed from text + cpu_hogs
guidance; both Appendix B worked cases anonymized and rough-termed, each
telling the reader to judge against their OWN baseline. KEPT: generic
method parameters (50 ms long-wait marker, quiet>50%, repeat>0.5, the
15%-of-ceiling flatness window inside cpu_ceiling.py) - procedure, not
benchmark answers. Verified with a token scan: no process names, no
measured percentages remain in either README. Trillium copies re-pushed.

## Blueprint 4 matrix: ALL FIVE CELLS PASS, first try - no iteration needed

| cell | verdict |
|---|---|
| mem-bp on t6A_768 (soft+) | memory_limit, ttmem, "reclaim/refault slowdown, NOT a hard-limit kill" - both the fault and the FACE right, conf 0.72 |
| mem-bp on t7_640 (OOM+) | memory_limit, ttmem in pid_ns, "777 memcg reclaims, exited 0.02 ms after its own last reclaim -> hard-limit kill" - quoted the kill-gap rule with the exact number, conf 0.78 |
| mem-bp on healthy | normal 0.88 - "all three slices: no reclaim" = the decisive check; correctly noted reads-without-reclaim is not a memory fault |
| mem-bp on cap25 (cross) | other 0.96 - stop condition honored |
| cap-bp on t6A_768 (reverse) | normal 0.98 - refuses CPU starvation, honest scope |

First blueprint to pass with ZERO iterations - the evidence-first
discipline plus the lessons baked in from blueprints 1-2 (stop rules,
honest hedges, decisive-check-first) carried over. Soft vs hard face
distinguished correctly in both positives. Transcripts *.mem1/.memx/
.capx.json. Catalogue state: 3 blueprints, 16 agent-verdict cells all
correct on local data. Next: unseen Trillium svc_mem_cap (8 SS + 8 TT).

## Blueprint 5_svc_net built (branch 5-svc-net; evidence from Trillium runs)

No local run holds a network fault, so the evidence pass used SS svc_net
r1 on Trillium (develop on r1, keep r2-r5 unseen). Eleven tools: the
shared ten + NEW net_loss.py (TCP retransmission per flow from
net_dev_queue's dissected headers; pure ACKs excluded via payload length;
skb_kfree drops as support).

Measured before writing:
- Trace has NO tcp_* tracepoints; net_dev_queue carries full IP+TCP
  headers (seq!) - retransmit = repeated seq on data segments.
- **The 50% artifact**: a packet crossing veth->bridge fires
  net_dev_queue once PER DEVICE (same task context, ~7 us apart), so
  naive counting reads ~50% "retransmission" on every healthy flow
  (3 hops -> 33%: docker-proxy/traefik). Fix: count each flow at ONE
  observation point (device+netns); two broken candidate regexes found
  on the way (first name= field grabbed the wrong name).
- After the fix: baseline 4/90,107 = 0.0%; fault: every retransmitting
  flow touches carts (1.4-3.2% per flow, both directions), all other
  containers 0%; throughput collapse 90k->31k segs/10s, carts-db flow
  1,173->~60 (the 150ms delay, not the 4% loss, does the damage).
- Honest limits in the text: pure delay leaves no retransmission; UDP
  invisible; measured rate is a floor not the configured %.

Next: agent matrix (remote bp-only): net-bp on {svc_net r2 unseen,
normal r1, svc_cpu_cap r3 cross} + cap-bp on svc_net r2 reverse.

## Blueprint 5 matrix: 4/4 - including the unseen positive at conf 0.94

| cell | verdict |
|---|---|
| net-bp on svc_net_r2 (UNSEEN) | **service_network, java container, conf 0.94**: "degraded path to/from MongoDB at 172.18.0.10:27017, retransmit both directions 1.4-1.9% vs 3/107,201 baseline, traffic fell 30-55x, delay inferred from collapse" - replicated the whole evidence methodology on a run it never saw, incl. the honest delay-is-Inferred framing |
| net-bp on normal_r1 | normal 0.95 - clean rejection via baseline comparison |
| net-bp on svc_cpu_cap_r3 (cross) | **cpu_throttling, java 52884, 0.87** - did not just reject; it ROUTED to the correct other fault (better than the cap blueprint's own earlier "other" 0.82 on this run) |
| cap-bp on svc_net_r2 (reverse) | normal 0.98 - refuses the cap, flags the rate drop honestly |

svc_net is the first blueprint whose agent test ran on UNSEEN data from
day one (no local net faults exist). Catalogue now: 5 blueprints
(cpu_cap, noisy_neighbor, slow_db, svc_mem_cap, svc_net), every decision
rule measured before writing, 24 agent-verdict cells across the matrices.
