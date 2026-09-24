#!/usr/bin/env python3
"""Generate an agent skill from a blueprint, and validate the blueprint first.

A blueprint is the human-facing, reviewable record of one solved investigation. A skill is
what the agent is actually handed. Generating one from the other means the two can never
drift, and it is the reason the blueprint is the artifact we maintain.

Leakage: fields listed under `harness_only` (labelled run ids) and `decision.fault_type`
carry the answer. They are used for scoring and are NEVER written into the skill body.

    python3 blueprint_to_skill.py --validate blueprints/*.json
    python3 blueprint_to_skill.py --out agentic-rca/skills-generated blueprints/*.json
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# Words that would hand the agent the answer if they appeared in the skill body.
LEAK_TOKENS = ["noisy_neighbor", "slow_db", "anomaly_cpu", "anomaly_mem", "anomaly_disk",
               "anomaly_net", "svc_cpu_cap", "svc_mem_cap", "svc_net", "queue_backlog",
               "error_storm", "dependency_outage", "aggressive", "subtle", "_r1", "_r2", "_r3",
               "sockshop", "trainticket", "anomaly-cpu-stress", "noisy-neighbor"]

REQUIRED = ["id", "version", "problem", "reproduction", "collection_order",
            "processing", "outputs", "decision", "provenance"]

PROVIDERS = os.path.join(os.path.dirname(HERE), "providers.json")
THRESHOLDS = os.path.join(os.path.dirname(HERE), "thresholds.json")


def load_thresholds():
    """name -> {value, unit, transfers, measured, used_by}. The single source for every
    number a blueprint decides on. Blueprints quote these by {NAME} rather than writing the
    figure, so the document and blueprint_decide.py cannot disagree."""
    try:
        with open(THRESHOLDS, encoding="utf-8") as fh:
            return json.load(fh).get("thresholds", {})
    except (OSError, json.JSONDecodeError):
        return {}


def fill_thresholds(text, th):
    """Substitute {NAME} with the measured value, for the agent-facing skill.

    The agent gets a real number - Mahsa's finding is that a description is not enough. The
    blueprint keeps the name, so editing thresholds.json moves every skill at once.

    The NUMBER only, never the unit: the sentence around it already says what the number
    counts, and appending the unit produced "450 requests/s per x of interrupt rise requests
    per second for each unit of rise in device interrupt time".
    """
    def one(m):
        t = th.get(m.group(1))
        if not t:
            return m.group(0)
        v = t["value"]
        return ("%g" % v) if isinstance(v, (int, float)) else str(v)
    return re.sub(r"\{([A-Z][A-Z0-9_]*)\}", one, text)


def load_providers():
    """capability id -> registry entry. A blueprint declares capabilities; this file binds
    them to whatever tool is actually available. Keeping that split is what makes the
    blueprint portable across tools instead of being a script wrapper."""
    try:
        with open(PROVIDERS, encoding="utf-8") as fh:
            return json.load(fh).get("capabilities", {})
    except (OSError, json.JSONDecodeError):
        return {}


def bind(cap_id, providers):
    """Resolve a capability to the first implemented provider. Returns (run, provider_id)."""
    cap = providers.get(cap_id)
    if not cap:
        return None, None
    for pr in cap.get("providers", []):
        if pr.get("status") == "implemented" and pr.get("run"):
            return pr["run"], pr["id"]
    return None, None


def validate(bp: dict, path: str) -> list:
    """Structural checks the schema cannot express, plus the ones that actually bite."""
    errs = []
    for k in REQUIRED:
        if k not in bp:
            errs.append(f"missing top-level field: {k}")
    if errs:
        return errs

    if not re.fullmatch(r"[a-z0-9-]+", bp["id"]):
        errs.append(f"id must be kebab-case: {bp['id']!r}")

    p = bp["problem"]
    if not p.get("discriminators"):
        errs.append("problem.discriminators is empty - a blueprint without discriminators "
                    "cannot be told apart from its look-alikes")
    for i, d in enumerate(p.get("discriminators", [])):
        for f in ("signal", "this_problem", "not_this_problem"):
            if not d.get(f):
                errs.append(f"discriminator[{i}] missing {f}")
        # EVIDENCE-FIRST RULE: a discriminator is a research claim. It may only be stated
        # if it was measured on our data, and the measurement must be pointed at.
        if not d.get("evidence"):
            errs.append(f"discriminator[{i}] ({d.get('signal','?')}) has no `evidence` - "
                        "every discriminator must cite the measurement that proved it. "
                        "Measure first (lib/measure_wait_signature.py), then author.")
        elif not any(t in d["evidence"].upper() for t in ("MEASURED", "EVIDENCE/", "RESULTS/")):
            errs.append(f"discriminator[{i}] evidence does not reference a measurement or an "
                        "evidence/ results/ artifact: " + d["evidence"][:70])

    # A step declares a CAPABILITY, never a tool — that is what keeps the blueprint portable
    # (Naser's architecture). Binding must still resolve to a real command, so Mahsa's rule
    # holds where it matters: what reaches the agent is an exact callable, not a description.
    providers = load_providers()
    for i, s in enumerate(bp.get("processing", [])):
        cap, run = s.get("capability"), s.get("run", "")
        if not cap and not run:
            errs.append(f"processing[{i}] declares neither a `capability` nor a `run`")
        elif cap:
            if cap not in providers:
                errs.append(f"processing[{i}] needs capability {cap!r}, absent from providers.json")
            elif not bind(cap, providers)[0]:
                errs.append(f"processing[{i}] capability {cap!r} has no IMPLEMENTED provider — "
                            "the blueprint cannot execute in this environment")
        elif not re.match(r"^(python3?|bash|sh|babeltrace2|TZ=\S+|cp|grep|awk|\./|\S+\.sh)\b", run):
            errs.append(f"processing[{i}].run does not look like a command: {run[:60]!r}")
        if not s.get("produces"):
            errs.append(f"processing[{i}] does not say what it produces")
        # PORTABILITY, and a leak. A step may only ask for inputs an operator working a live
        # incident actually has: where the traces are, which window, where to write. It may
        # NOT ask for our dataset's coordinates - and <family> is the ground-truth fault name,
        # so requiring it both breaks deployment anywhere else AND hands the answer to the
        # model the harness is supposed to be testing.
        blob = json.dumps(s)
        for bad, why in (("<app>", "our dataset's application name"),
                         ("<run_id>", "our dataset's run identifier"),
                         ("<family>", "THE GROUND-TRUTH FAULT NAME - this is the answer"),
                         ("/scratch/", "a path on our cluster")):
            if bad in blob:
                errs.append(f"processing[{i}] requires {bad} ({why}). A blueprint may only "
                            "need <trace_dir>, <window> and <out>")

    for c in bp.get("capabilities_required", []):
        if c.get("id") not in providers:
            errs.append(f"capabilities_required lists {c.get('id')!r}, absent from providers.json")

    if not (bp.get("applicability") or {}).get("apply_when"):
        errs.append("no `applicability.apply_when` — a blueprint must say when it applies, or "
                    "a selector cannot choose it")
    if not (bp.get("stopping_conditions") or {}).get("conclude"):
        errs.append("no `stopping_conditions.conclude` — a blueprint must say when the "
                    "investigation is finished")

    # Every declared output should be produced by some step.
    produced = " ".join(str(s.get("produces", "")) for s in bp.get("processing", []))
    for o in bp.get("outputs", []):
        if o["path"] not in produced:
            errs.append(f"output {o['path']} is declared but no processing step produces it")

    if not bp["collection_order"].get("kernel_events"):
        errs.append("collection_order.kernel_events is empty - a blueprint must say exactly "
                    "what to record, not 'kernel data'")

    d = bp["decision"]
    if not d.get("rule_out"):
        errs.append("decision.rule_out is empty - a blueprint must say when NOT to conclude this")

    # ---- NO SILENT DRIFT BETWEEN THE DOCUMENT AND THE ENGINE ------------------------------
    # The numbers used to be written twice: as prose here, and as Python literals in
    # blueprint_decide.py. Nothing compared them, and they drifted badly - host-disk-saturation
    # still told a reader "at least 2000 disk requests per second" after the engine had
    # replaced that with a ratio, and service-memory-cap documented an IRQ_X=2.5 / 500 req/s
    # pair that the engine's own comment records as having scored 3/16 before replacement.
    # A reader following the blueprint was following a rule we had measured and rejected.
    #
    # Now a blueprint quotes a threshold by {NAME} and the value is substituted at generation
    # time from thresholds.json. These checks make the quoting mandatory and the names real.
    th = load_thresholds()
    used = d.get("uses_thresholds") or []
    for name in used:
        if name not in th:
            errs.append(f"decision.uses_thresholds names {name!r}, absent from thresholds.json")
        elif bp["id"] not in th[name].get("used_by", []):
            errs.append(f"threshold {name} does not list {bp['id']} in its used_by - "
                        "the two directions must agree or one of them is stale")
    prose = " ".join(list(d.get("verdict_when", []))
                     + [r.get("when", "") for r in d.get("rule_out", [])])
    for ref in set(re.findall(r"\{([A-Z][A-Z0-9_]*)\}", prose)):
        if ref not in th:
            errs.append(f"decision prose refers to {{{ref}}}, absent from thresholds.json")
        elif ref not in used:
            errs.append(f"decision prose refers to {{{ref}}} but uses_thresholds omits it")
    # A bare number where a threshold belongs is exactly how the last drift started, so the
    # rule here is blunt on purpose: in verdict_when, ANY digit must come from a {NAME}.
    # An earlier version of this check tried to match units ("N requests per second") and
    # missed the real bug, because the prose read "2000 disk requests per second" - one word
    # in the wrong place and the check was blind. Matching units is guesswork; matching digits
    # is not. rule_out stays lenient: it quotes other faults' measured ranges as context, and
    # those are descriptions rather than bars this blueprint applies.
    for i, v in enumerate(d.get("verdict_when", [])):
        if re.search(r"\d", re.sub(r"\{[A-Z][A-Z0-9_]*\}", "", v)):
            errs.append(f"decision.verdict_when[{i}] contains a bare number - every figure a "
                        f"blueprint decides on must be quoted as {{NAME}} from thresholds.json "
                        f"so it cannot drift from the engine: {v[:72]!r}")

    if str(bp["provenance"].get("verified_by", "")).startswith("PENDING"):
        errs.append("NOTE: not yet human-verified (provenance.verified_by is PENDING)")

    return errs


def _harness_leak_re():
    """The evaluation harness lints every skill it loads and REFUSES a dirty library. Keeping a
    second, private word list here was the bug: this file passed a skill the harness then
    rejected, and the whole with/without job died at load time. Borrow the harness list so the
    generator can never emit something the consumer will refuse."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
        import skillreg                                                    # noqa: PLC0415
        return skillreg._FORBIDDEN_RE
    except Exception:                                                      # noqa: BLE001
        return None                                    # harness absent — local list still applies


def leak_scan(text: str) -> list:
    low = text.lower()
    hits = {t for t in LEAK_TOKENS if t.lower() in low}
    rx = _harness_leak_re()
    if rx:
        hits |= {m.group(0).lower() for m in rx.finditer(text)}
    return sorted(hits)


# How to reach each capability with a raw kernel trace and the six read-only tools.
#
# A blueprint step names a capability and, normally, a command bound to it. In phase 1 there is
# no shell, so the command is dropped - but dropping it alone left the agent holding a step it
# had no idea how to perform. These lines close that gap. They say which tool and which events,
# not what the answer is: no thresholds, no windows, no expected verdict. A step with no recipe
# here keeps its capability and its expectation and is simply marked as not reachable, which is
# itself information - it tells the agent which parts of the method it cannot run, instead of
# leaving it to guess or to fake.
KERNEL_RECIPES = {
    "trace.stage_ctf":
        "already done - the trace is loaded. ctf_timespan gives its real start and end.",
    "kernel.scheduler.oncpu_attribution":
        "query_ctf on sched_switch over each range, and read top_procnames: that is who was "
        "getting the CPU. ctf_procdiff between the two ranges names who changed.",
    "kernel.scheduler.runqueue_delay":
        "the delay is sched_waking to the sched_switch that runs the thread. You cannot join "
        "those two per thread with these tools, so use the rate of sched_waking against "
        "sched_switch as a proxy, and say in your evidence that it is a proxy.",
    "kernel.syscall.blocking_duration":
        "query_ctf on syscall_entry_poll, syscall_entry_epoll_wait, syscall_entry_recvfrom, "
        "syscall_entry_read per range. Rates only - durations need pairing with the exits, "
        "which these tools cannot do. Say so rather than implying you measured duration.",
    "kernel.interrupt.time_attribution":
        "query_ctf on irq_handler_entry and softirq_entry per range, compared by rate.",
    "process.creation_attribution":
        "ctf_proclife shows arrivals and departures directly. sched_process_fork and "
        "sched_process_exec rates via query_ctf show how fast processes are being created.",
    "storage.io_attribution":
        "query_ctf on block_rq_issue and block_rq_complete per range, with top_procnames for "
        "who is issuing the I/O. Rates, not latencies.",
    # CORRECTED 22-09-2026. This line used to say a retransmission rate "is not measurable",
    # written from the general fact that there is no tcp_retransmit_skb tracepoint - without
    # checking what this profile actually captures. It captures the FULL TCP header on
    # net_if_receive_skb, `seq` included, which is how the campaign measured 51.9-61.8%
    # retransmission from these very traces.
    #
    # The cost of that sentence was measured: it told the agent its deciding check was
    # impossible, and the blueprint arm then abstained on 13-14 of 30 anomaly_net windows
    # against 0-1 without the blueprint. A blueprint that says the answer cannot be reached is
    # worse than no blueprint, and the agent was right to refuse - it was told a falsehood.
    # Added 23-09 after measuring it, not after thinking it would work. The agent answered
    # `host` on svc_net in 10-11 of 12 cells on both applications, and WHERE scored 0/60 in the
    # published results - which looked like "a kernel trace cannot localise a per-service
    # network fault". It can. See the numbers in the recipe text; they are what a blueprint is
    # allowed to assert.
    # Added 23-09 after three statistics failed. The failures are the useful part and are
    # written into the recipe, because the obvious one is actively misleading here.
    "kernel.scheduler.cpu_ceiling":
        "sched_stat_runtime carries `runtime` in nanoseconds, and the index sums it per "
        "container per 100 ms bucket in the `value_sum` column - so with run_python you can "
        "get each container's actual CPU time, which no count of events gives you. "
        "DO NOT rank containers by how much their CPU FELL. Measured: the capped container "
        "ranked #15 of 18 that way, because it falls to about 40% of its baseline while the "
        "median container falls to about 18% - when one service stalls, the whole application "
        "slows and everything else loses MORE CPU than the throttled service does. Ranking by "
        "the biggest drop finds victims. "
        "What works, measured 3 of 3: a quota is a CEILING, so the throttled container's CPU "
        "per bucket stops varying and sits flat. Take only containers actually consuming CPU - "
        "a quota cannot show on one that never approaches it, and a nearly idle series is "
        "trivially flat - then among those compare p95 to p50 of per-bucket CPU. The flattest "
        "is the throttled one. Confirm it by reading its ABSOLUTE rate: a quota is a round "
        "number, and measured it sat at 0.198-0.202 CPU against a 0.2 cap while using 0.51 "
        "before. Report that rate; it tells the operator what the quota was set to. "
        "If NO busy container is pinned flat, say so. A cap set far above what a service "
        "actually uses never binds, and then there is nothing here to find - which is a real "
        "finding, not a failure to look.",
    "network.per_container_rate_ranking":
        "every network event carries pid_ns, and one pid_ns is one container, so the impaired "
        "path IS attributable. Use run_python: sum `count` for net_dev_xmit, "
        "net_if_receive_skb, net_dev_queue and net_if_rx per pid_ns over a quiet baseline "
        "range, do the same over the range you suspect, and divide the second by the first. "
        "Rank the containers by that ratio, lowest first, and report the lowest by its pid_ns. "
        "MEASURED: on one of the two applications the container whose interface was impaired "
        "ranked FIRST on this measure in 3 of 3 runs, collapsing to 0.155-0.184 of its baseline "
        "packet rate while the median container held at 0.63-0.73. On the other application the "
        "same measure produced a clear outlier too, but which container it was could not be "
        "confirmed, so treat the ranking as a strong lead there and say so rather than claiming ""certainty. "
        "The same numbers tell you the SCOPE, which interface counts were measured not to: if "
        "ONE container is far below while the rest sit near 1, one service's path is impaired; "
        "if EVERY container fell together - measured 0.075-0.089 median on a host-wide network "
        "fault - the host's networking is impaired and no single container is the culprit.",
    "network.retransmission_rate":
        "the sequence numbers ARE in this trace: net_if_receive_skb carries the full IP and "
        "TCP header, so `seq` repeating on the same flow is a retransmission. Read raw lines "
        "with ctf_lines and look for repeated seq values on one flow. Be careful about what "
        "you can claim: ctf_lines returns at most 40 lines over a narrow range, so you can "
        "show retransmission IS or IS NOT happening, but you cannot compute a rate over a "
        "window with these tools. Say which of the two you did, and do not report a percentage "
        "you did not measure.",
    "network.egress_attribution":
        "query_ctf on net_dev_xmit with top_procnames, and ctf_procdiff on the same event to "
        "see which process's traffic changed.",
    "syscall.error_attribution":
        "query_ctf on syscall_exit_* for the calls you care about, then ctf_lines over a narrow "
        "range to read the actual return values. Error codes are in the raw lines only.",
    "metrics.container.cpu_attribution":
        "there are no container metrics here. The kernel equivalent is per-process on-CPU "
        "attribution: query_ctf on sched_switch with top_procnames, plus ctf_procdiff to find "
        "a process present in one range and absent from the other. Process names are the "
        "kernel's, not container names.",
    "traces.call_graph.convergence":
        "NOT REACHABLE from a kernel trace - there are no spans, so there is no call graph. Do "
        "not guess at one. Say the check could not be run, and do not treat its absence as "
        "either supporting or refuting the blueprint.",
    "verdict.apply_rules":
        "do this yourself, from the numbers your own tool calls returned. Quote them.",
    "verdict.dependency_wait":
        "do this yourself, from the numbers your own tool calls returned. Quote them.",
    "report.recommended_action":
        "write it in your own words in the diagnosis.",
    "report.decision_card":
        "NOT REACHABLE - no plotting here. Skip it; it does not affect the diagnosis.",
}


def to_skill(bp: dict, kernel_only: bool = False) -> str:
    """Render the agent-facing skill. Answer-bearing fields are deliberately excluded.

    kernel_only drops the resolved command bindings. In phase 1 the agent has a raw
    kernel trace and four read-only tools - no shell, no prometheus, no cadvisor - so
    every `run [...]` line names something it cannot do. Worse, three of them pass
    `--gt <window>`, the ground-truth injection window, which is the one thing the
    agent is supposed to work out for itself. The capability and the expectation stay:
    those are the method. Only the binding goes, which is what the blueprint already
    says a binding is - environment-specific and replaceable.
    """
    p, c, d = bp["problem"], bp["collection_order"], bp["decision"]

    app = bp.get("applicability", {})
    sig = ["## When this applies"]
    for x in app.get("apply_when", []):
        sig.append(f"- {x}")
    if app.get("do_not_apply_when"):
        sig.append("")
        sig.append("Do NOT use this blueprint when:")
        for x in app["do_not_apply_when"]:
            sig.append(f"- {x}")
    if app.get("cheap_precheck"):
        sig += ["", f"Cheapest check first: {app['cheap_precheck']}"]

    sig += ["", "## Problem signature"]
    for s in p["symptoms"]:
        sig.append(f"- {s}")
    sig.append("")
    sig.append("Telling it apart from its look-alikes:")
    for disc in p["discriminators"]:
        sig.append(f"- **{disc['signal']}** — this problem: {disc['this_problem']}. "
                   f"Not this problem: {disc['not_this_problem']}.")

    retracted = p.get("unverified_do_not_claim") or []

    order = ["## What to look at first",
             "The signals below are sufficient for this problem; you do not need everything.",
             ""]
    order.append(f"- kernel: {', '.join(c['kernel_events'])}")
    if c.get("metrics"):
        order.append(f"- metrics: {', '.join(c['metrics'])}")
    if c.get("traces"):
        order.append(f"- traces: {'; '.join(c['traces'])}")
    if c.get("logs"):
        order.append(f"- logs: {'; '.join(c['logs'])}")
    if c.get("why_these"):
        order += ["", f"Why this set: {c['why_these']}"]

    providers = load_providers()
    if kernel_only:
        steps = ["## Investigation blueprint",
                 "Each step names the capability it needs, how to get at it with the tools "
                 "you have, and what a correct result looks like. There are no commands: you "
                 "have a raw kernel trace and six read-only query tools, and nothing else. "
                 "The 'with your tools' line is a starting point, not an instruction - if you "
                 "see a better way with the same tools, take it and say what you did. A step "
                 "marked NOT REACHABLE cannot be done from kernel data: skip it, say you "
                 "skipped it, and do not treat its absence as evidence either way.", ""]
    else:
        steps = ["## Investigation blueprint",
                 "Each step names the capability it needs. The command shown is the binding "
                 "resolved for THIS environment; another environment may bind a different tool "
                 "to the same capability without changing the procedure.", ""]
    for i, s in enumerate(bp["processing"], 1):
        steps.append(f"{i}. {s['step']}")
        cap = s.get("capability")
        run = s.get("run")
        if cap:
            bound, prov = bind(cap, providers)
            steps.append(f"   needs: `{cap}`")
            if kernel_only:
                steps.append("   with your tools: %s"
                             % KERNEL_RECIPES.get(cap, "no direct equivalent from a kernel "
                                                       "trace - say the step was not run."))
            elif bound:
                steps.append(f"   run [{prov}]: `{bound}`")
            run = run or bound
        elif run and not kernel_only:
            steps.append(f"   run: `{run}`")
        if s.get("expect"):
            steps.append(f"   expect: {s['expect']}")

    outs = ["## What to produce"]
    for o in bp["outputs"]:
        outs.append(f"- {o['kind']}: {o['contains']}")

    # The blueprint stores {NAME}; the agent is given the measured value. Keeping the name in
    # the document and the number in the skill is what stops the two from drifting apart.
    th = load_thresholds()
    res = ["## Resolution template", "Conclude this problem when ALL of:"]
    for v in d["verdict_when"]:
        res.append(f"- {fill_thresholds(v, th)}")
    res += ["", "Prefer a different explanation when:"]
    for r in d["rule_out"]:
        res.append(f"- {r['instead']} — {fill_thresholds(r['when'], th)}")
    res += ["", f"Root cause is: {d['root_cause_is']}"]

    stop = bp.get("stopping_conditions") or {}
    if stop:
        res += ["", "## When to stop"]
        if stop.get("conclude"):
            res.append(f"- Conclude when: {stop['conclude']}")
        if stop.get("stop_and_switch"):
            res.append(f"- Stop and switch: {stop['stop_and_switch']}")
        if stop.get("stop_insufficient"):
            res.append(f"- Evidence insufficient: {stop['stop_insufficient']}")
        if stop.get("max_evidence_rounds"):
            res.append(f"- Do not exceed {stop['max_evidence_rounds']} rounds of gathering "
                       "more evidence before reporting what is missing.")

    pol = bp.get("policies") or {}
    if pol:
        res += ["", "## Constraints you must respect"]
        if pol.get("collection_order_rule"):
            res.append(f"- {pol['collection_order_rule']}")
        if pol.get("max_collection_overhead_pct"):
            res.append(f"- Keep total added collection overhead under "
                       f"{pol['max_collection_overhead_pct']}%.")
        for x in pol.get("privacy", []):
            res.append(f"- {x}")
        appr = pol.get("approval") or {}
        if appr.get("requires_approval"):
            res.append("- These need human approval before you do them: "
                       + "; ".join(appr["requires_approval"]) + ".")

    suf = bp.get("evidence_sufficiency") or {}
    if suf:
        res += ["", "## If you are not confident enough"]
        if suf.get("confidence_floor"):
            res.append(f"- Do not report a diagnosis below {suf['confidence_floor']} confidence.")
        if suf.get("if_below_floor"):
            res.append(f"- {suf['if_below_floor']}")
        if suf.get("report_when_stuck"):
            res.append(f"- {suf['report_when_stuck']}")

    # How this problem looks on different system shapes. Measured on more than one
    # application, and kept as separate pictures rather than averaged into one threshold - a
    # number learned on one architecture does not describe another, and saying so is the
    # point of writing the blueprint down.
    scen = (bp.get("scenarios") or {}).get("cases") or []
    if scen:
        res += ["", "## How this looks on different systems",
                "The same fault does not look the same everywhere. Work out which case you are",
                "in before you judge the numbers."]
        for s in scen:
            res.append(f"\n**{s['scenario']}** — recognise by: {s['recognise_by']}")
            res.append(f"- What you see: {s['what_you_see']}")
            if s.get("confidence"):
                res.append(f"- How much to trust it: {s['confidence']}")
            if s.get("do_this_instead"):
                res.append(f"- Instead: {s['do_this_instead']}")

    adapt = bp.get("adaptation_rules") or []
    if adapt:
        res += ["", "## If the evidence does not fit"]
        for r in adapt:
            res.append(f"- If {r['if']}, then {r['then']}.")

    warn = []
    if retracted:
        warn = ["## Signals that do NOT work for this problem",
                "Each of these was measured on our own data and found unusable. Do not reason",
                "from them, and do not let their absence argue against this problem:"]
        for r in retracted:
            # `measurement` names fault families and is for the human record only; the skill
            # gets `agent_note`, which says the same thing without the answer vocabulary.
            warn.append(f"- {r['claim']} — **{r['status']}**. "
                        f"{r.get('agent_note') or ''}")

    body = "\n".join(sig + [""] + order + [""] + steps + [""] + outs + [""] + res
                     + ([""] + warn if warn else []))

    fm = [
        "---",
        f"name: {bp['id']}",
        f"version: {bp['version']}",
        f"authored_by: {bp['provenance']['authored_by']}",
        f"generated_from: blueprints/{bp['id']}.json",
        # No trailing comment here. skillreg parses frontmatter as split(":", 1) and keeps the
        # whole remainder, so an inline note becomes PART OF the value — `covers` then never
        # equals the ground-truth family and every selection scores wrong. (It is harness
        # metadata for scoring and LOFO, stripped before the model sees anything.)
        f"covers: {d.get('fault_type', '')}",
    ]
    if bp.get("mutually_exclusive_with"):
        fm.append(f"mutually_exclusive_with: {', '.join(bp['mutually_exclusive_with'])}")
    fm.append("---")

    return "\n".join(fm) + "\n" + body + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("blueprints", nargs="+")
    ap.add_argument("--out", default="", help="write skills here; omit to validate only")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--kernel-only", action="store_true",
                    help="drop the resolved command bindings: phase 1 gives the agent "
                         "a raw kernel trace and read-only query tools, so every "
                         "command line names something it cannot run, and three of "
                         "them pass the ground-truth window")
    a = ap.parse_args()

    paths = []
    for pat in a.blueprints:
        paths += sorted(glob.glob(pat))
    if not paths:
        sys.exit("no blueprints matched")

    bad = 0
    for path in paths:
        try:
            bp = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"FAIL {path}: invalid JSON: {e}"); bad += 1; continue

        errs = validate(bp, path)
        hard = [e for e in errs if not e.startswith("NOTE:")]
        for e in errs:
            print(("  WARN " if e.startswith("NOTE:") else "  ERR  ") + e)
        if hard:
            print(f"FAIL {path}: {len(hard)} problem(s)"); bad += 1; continue

        skill = to_skill(bp, kernel_only=a.kernel_only)
        # Scan the BODY only. The frontmatter carries `covers:` on purpose — it is harness
        # metadata for scoring and leave-one-out, and skillreg never puts it in the prompt.
        body_only = skill.split("---", 2)[-1]
        leaks = leak_scan(body_only)
        if leaks:
            print(f"FAIL {path}: skill body leaks answer tokens: {leaks}"); bad += 1; continue

        print(f"OK   {path}  ({len(bp['processing'])} steps, "
              f"{len(bp['collection_order']['kernel_events'])} kernel events, "
              f"{len(bp['problem']['discriminators'])} discriminators)")

        if a.out:
            os.makedirs(a.out, exist_ok=True)
            dst = os.path.join(a.out, bp["id"] + ".md")
            open(dst, "w", encoding="utf-8").write(skill)
            print(f"     -> {dst}")

    print(f"\n{len(paths) - bad}/{len(paths)} blueprints usable")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
