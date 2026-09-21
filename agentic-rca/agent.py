#!/usr/bin/env python3
"""The LLM RCA agent — drives the four telemetry tools to a structured diagnosis.

Given a run (one incident) it exposes the 4 deterministic tools (traces/logs/metrics/kernel) to a
tool-using LLM and lets it investigate freely, then commit to the output contract
    { root_cause_service, fault_type, evidence, confidence }
While it runs it records the **trajectory** (every tool call, target service, result-size, next
tool) + token usage — that is RQ2's dependent variable, and the byte totals feed RQ4's cost axis.
It also captures a **full-fidelity transcript** (transcript.py / TRANSCRIPTS.md): every prompt, raw
API response (including any reasoning text) and full tool result — the publishable audit record.

Two provider-native loops (tool-use requires provider-specific message threading): Anthropic and the
OpenAI-compatible family (azure/gemini/openai/ollama); model id / temperature / max_tokens come from
`config.py` so the model is still a config knob.

Degradation note: the agent is HELD FIXED. To study telemetry degradation you pass a degraded Run
(same interface) — the agent code never changes. That keeps Axis A (data) and Axis B (agent) clean.
"""
from __future__ import annotations
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import context_builder
import ctf_tool
from ctf_tool import TOOL_DEF as _CTF_TOOL_DEF
from ctf_tool import TIMELINE_DEF as _CTF_TIMELINE_DEF
from ctf_tool import TIMESPAN_DEF as _CTF_TIMESPAN_DEF
import leakguard
import shared_context
import skillreg
import source_tool
import transcript as T
from tools import RunTools

# tool results sent to the model are capped at this many chars (full result stays in the transcript)
SENT_CAP = 6000

# fault vocabulary the agent must choose from (aligns with ground_truth families for scoring)
FAULT_TYPES = [
    "cpu_saturation", "memory_pressure", "disk_io", "network_latency", "db_latency",
    "dependency_outage", "error_storm", "noisy_neighbor", "cpu_throttling",
    "memory_limit", "service_network", "queue_backlog", "normal",
]

_SYS_HEAD = (
    "You are a senior SRE doing root-cause analysis of ONE incident in a microservice system. "
    "An anomaly was detected in a known time window. Your read-only telemetry tools compare the "
    "pre-incident BASELINE to the incident window.\n"
    "\n"
    "METHOD:\n"
    "1. SURVEY: list_services, then the query tools WITHOUT a service filter, to see what CHANGED "
    "system-wide. Signals equally present in baseline (chronic errors, standing noise) are "
    "background — never root cause. High absolute counts mean nothing unless they changed.\n"
    "2. SHAPE the blast radius: (a) many unrelated services degrade together -> suspect a "
    "HOST-level cause: check service 'host' (node metrics, host-kernel) and look for an "
    "unexplained workload/container that appears or spikes at onset; (b) degradation follows a "
    "call path -> walk it with query_topology; (c) one service (or only its callers) degrades -> "
    "suspect that service or its resource limits.\n"
    "3. CULPRIT vs VICTIM: a victim waits on something else (slow edges TOWARD a dependency, "
    "off-CPU external wait, timeouts). The culprit is the deepest component whose degradation is "
    "NOT explained by one of ITS dependencies. Follow slow topology edges downstream until they "
    "stop; verify the endpoint with kernel evidence.\n"
    "4. WHY: use query_kernel to explain the mechanism — on-CPU saturation vs CPU-starved "
    "(runnable wait) vs disk wait vs external I/O wait; throttling; memory reclaim. A component "
    "slow WITHOUT internal saturation is being slowed from outside (dependency, host, or induced "
    "latency). When code-level confirmation helps (what a timeout, retry policy, or error string "
    "actually does), query_source can search and read the application's source.\n"
    "5. Only then submit_diagnosis, citing the decisive baseline->incident changes.\n"
    "\n"
)

_FAULT_VOCAB = (
    "FAULT TYPES (operational definitions — pick the closest):\n"
    "- cpu_saturation: host-wide CPU pressure; an extra workload or spike consumes host CPU, many "
    "services see contention.\n"
    "- noisy_neighbor: a co-tenant workload consumes host resources while user-facing KPIs stay "
    "near-normal; contention shows mainly in kernel scheduling signals.\n"
    "- disk_io: host disk saturated (host io_time / block latency up, all disk users affected).\n"
    "- memory_pressure: host memory exhausted (reclaim/writeback activity, available memory "
    "collapsing, swap).\n"
    "- network_latency: host-wide network delay/loss (cross-service calls slow everywhere, no "
    "single culprit path).\n"
    "- db_latency: a DATASTORE answers slowly (callers slow on DB calls; the datastore shows "
    "external/IO wait or induced latency WITHOUT cpu/memory saturation). Prefer this over "
    "dependency_outage when the slow component is a database and traffic still succeeds.\n"
    "- dependency_outage: a dependency is DOWN or FROZEN — calls to it hang to timeout or fail "
    "with connection errors and it produces little/no successful traffic (not merely slow).\n"
    "- error_storm: a service returns bursts of application errors/5xx; latency only moderately "
    "affected.\n"
    "- cpu_throttling: ONE service pinned by its CPU limit (its throttled-seconds jump; only it "
    "slows).\n"
    "- memory_limit: ONE service hits its memory cap (GC pressure/OOM kills/restarts at a flat "
    "memory ceiling).\n"
    "- service_network: ONE service's network path is degraded (only traffic through it is "
    "slow/lossy; host network fine).\n"
    "- queue_backlog: an async queue/consumer silently backs up (producer healthy, consumer "
    "idle/lagging, backlog grows; few user-visible errors).\n"
    "- normal: no injected fault evident.\n"
    "\n"
)

_SYS_RULES = (
    "RULES: root_cause_service is the culprit component as named in telemetry — name the "
    "unexplained workload/container itself if a co-tenant is the cause, or 'host' for host-wide "
    "resource causes with no visible culprit workload. Distinguish victims from the culprit. Be "
    "economical with tool calls; never guess before checking baseline->incident evidence."
)

SYSTEM = _SYS_HEAD + _FAULT_VOCAB + _SYS_RULES

# ---------------------------------------------------------------------------
# Phase 1 of the blueprint study: a raw LTTng kernel trace and nothing else.
#
# The default prompt above cannot be reused. It opens with "an anomaly was detected in a known
# time window" and "your tools compare the pre-incident BASELINE to the incident window" - both
# false here, and both give away the one thing the agent is supposed to work out for itself.
# Its METHOD then names list_services, query_topology, query_kernel and query_source, none of
# which are offered. A prompt that describes tools the agent does not have is how the first
# pilot ended up reporting "normal" because the modalities it expected came back empty.
_KO_HEAD = (
    "You are a senior SRE handed ONE raw kernel trace from a microservice host. Nobody has "
    "told you whether anything went wrong, when, or where. There is no alert, no known "
    "incident window, and no pre-computed baseline. Finding all of that is the job.\n"
    "\n"
    "YOUR ONLY EVIDENCE is the LTTng kernel trace, through three tools: ctf_timespan (how long "
    "the recording is), ctf_timeline (one event counted across the whole recording, bucketed, "
    "as a bar chart) and query_ctf (counts, rates, top processes and raw event lines over a "
    "range YOU choose). There are deliberately no metrics, logs or spans. That is the dataset, "
    "not a gap in it: never treat a missing modality as evidence that nothing happened.\n"
    "\n"
    "METHOD:\n"
    "1. ORIENT: ctf_timespan first, so you know the real start and end. Every later range must "
    "sit inside it. Timestamps are UTC.\n"
    "2. FIND THE WHEN: ctf_timeline on a few unrelated events (for example sched_switch, "
    "sched_wakeup, block_rq_issue, net_dev_xmit) across the FULL span. You are looking for a "
    "step, a spike or a collapse in one series that the others do not share. A step present in "
    "everything usually means the workload changed, not that the system misbehaved. Check the "
    "coverage line each call reports: if a scan was truncated, the quiet part may simply be the "
    "part you never read.\n"
    "3. FIND THE WHERE: query_ctf over the suspect range versus a quiet range you pick as your "
    "own baseline. Compare top processes between the two. The culprit is usually a process that "
    "is absent or negligible in the quiet range and dominant in the suspect one.\n"
    "4. FIND THE WHY, from the mechanism the kernel actually recorded: on-CPU saturation "
    "(sched_switch churn, one process monopolising), CPU starvation (long sched_wakeup to "
    "sched_switch delay), disk wait (block_rq_issue/block_rq_complete latency), network "
    "(net_dev_xmit/netif_receive_skb), lock or futex contention, memory reclaim, or a process "
    "exiting and respawning. Read a few raw event lines before you commit - counts alone can "
    "mislead.\n"
    "5. CONFIRM OR REJECT: state which check would have falsified your conclusion and whether "
    "you ran it. If the evidence genuinely shows a healthy system, 'normal' is a legitimate "
    "answer - but only after you have looked across the whole span, not because a tool came "
    "back empty.\n"
    "6. Then submit_diagnosis, with the incident_window you derived and the evidence for it.\n"
    "\n"
)

_KO_RULES = (
    "RULES: root_cause_service is the culprit as it appears in the kernel trace - the process "
    "or container name itself when one workload is responsible, or 'host' for a host-wide "
    "resource cause with no single visible culprit. Kernel process names are truncated to 15 "
    "characters; report what you saw. Distinguish victims (processes waiting) from the culprit "
    "(the process consuming). incident_window must come from your own evidence: an invented "
    "window is worse than 'unknown'. Never guess a fault type before you have located a change "
    "in time and attributed it to a process."
)

SYSTEM_KERNEL_ONLY = _KO_HEAD + _FAULT_VOCAB + _KO_RULES

_TOOL_DEFS = [
    {"name": "list_services", "description": "List the services/containers present in this incident.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "query_traces", "description": "SERVER-span latency (p50/p95/p99/count) per service in the incident window. Omit service for all.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_topology", "description": "Caller->callee edges from trace parent/child links with baseline vs incident p95 per edge, sorted by slowdown. Victims' slow edges point AT the culprit. Optional service filter = edges touching it.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_logs", "description": "Per-container error-rate CHANGE baseline vs incident + NEW error signatures (absent in baseline). Chronic signatures are flagged as such. Omit service for all.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_metrics", "description": "Resource signals (cpu/throttle/mem/net/fs) baseline vs incident window per container, ranked by movement. service='host' gives node-level host signals (cpu busy cores, disk io_time, mem available, net).",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_kernel", "description": "Kernel evidence per service, baseline vs incident: changed KPIs (syscall/block latency, disk, net, scheduler, memory reclaim), L3 deviation digests, L2 wait-attribution. 'host' = unattributed host-kernel activity.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_source", "description": "Search/read the application's source code (grep/glob/cat style). op='find_files': pattern is a glob, e.g. '**/*Order*.java'. op='search': pattern is regex or plain text, returns file:line matches (optional 'path' glob narrows it). op='read': 'path' + optional start_line/limit returns numbered lines. Use it to verify how a suspect service, endpoint, timeout, retry or error message is implemented.",
     "parameters": {"type": "object", "properties": {
         "op": {"type": "string", "enum": ["find_files", "search", "read"]},
         "pattern": {"type": "string", "description": "glob for find_files; regex/text for search"},
         "path": {"type": "string", "description": "file path for read; optional path glob filter for search"},
         "start_line": {"type": "integer"},
         "limit": {"type": "integer", "description": "lines to read (default 120, max 400)"}},
         "required": ["op"]}},
    # Raw-trace tools. Every other tool serves a pre-computed aggregation, which caps what the
    # agent can discover at whatever someone thought to aggregate in advance. These let it read
    # any tracepoint the kernel recorded, and - critically - FIND WHEN something happened
    # rather than being handed the injection window. None of them reads ground_truth.json.
    _CTF_TIMESPAN_DEF,
    _CTF_TIMELINE_DEF,
    _CTF_TOOL_DEF,
    {"name": "submit_diagnosis",
     "description": ("Commit the final root-cause verdict: WHAT went wrong, WHERE, and WHEN. "
                     "The window is part of the answer, not a detail - you were not told when "
                     "the incident was and finding it is half the job."),
     "parameters": {"type": "object", "properties": {
         "root_cause_service": {"type": "string", "description": "the single culprit service/container"},
         "fault_type": {"type": "string", "enum": FAULT_TYPES},
         "evidence": {"type": "string", "description": "1-3 sentences citing the decisive signals"},
         "confidence": {"type": "number", "description": "0..1"},
         # WHEN. Nothing told the agent this; it has to be derived from the trace, which is why
         # window_evidence is required alongside it - a guessed range that happens to overlap
         # is not a finding, and the two fields together let a human tell them apart.
         "incident_window": {"type": "string", "description":
                             "the time range the anomaly occupies, as 'HH:MM:SS - HH:MM:SS' in "
                             "trace clock time. Say 'unknown' if the evidence does not support "
                             "a range - a wrong window is worse than an admitted gap."},
         "window_evidence": {"type": "string", "description":
                             "what made you choose that range: which event, which tool call, "
                             "what changed at the boundary"}},
         "required": ["root_cause_service", "fault_type", "evidence", "confidence",
                      "incident_window", "window_evidence"]}},
]

# Optional ranked-answer mode (RQ: hit@k / MRR / MAP, comparable to the ranked-list baselines).
# OFF by default so the frozen single-verdict configuration is untouched: passing rank_k=0
# yields byte-identical tool schemas. When on, alternatives are EVIDENCE-ranked — a candidate
# without its own supporting evidence is dropped by the harness, so the list is not merely the
# model's next-most-likely tokens.
_ALTERNATIVES_PROP = {
    "type": "array",
    "description": ("Other candidates your evidence genuinely left open, most likely FIRST. "
                    "Do not pad: include a candidate only if you can cite evidence for it that "
                    "does not merely repeat the primary verdict. Omit entirely if the primary "
                    "verdict is the only one the evidence supports."),
    "items": {"type": "object", "properties": {
        "service": {"type": "string", "description": "candidate culprit service/container"},
        "fault_type": {"type": "string", "enum": FAULT_TYPES},
        "evidence": {"type": "string", "description": "the signal that keeps THIS candidate open"}},
        "required": ["service", "fault_type", "evidence"]},
}


# Phase 1 of the blueprint study is KERNEL TRACES ONLY - no logs, metrics or spans. The other
# query tools read derived frames that L0 bundles do not carry, so offering them does not merely
# waste calls: the agent reads their emptiness as evidence that nothing happened. In the first
# pilot it concluded "normal" partly because "query_metrics returned no metrics, query_kernel is
# unavailable, and there are no service spans/logs/topology edges". Absence of a tool's output
# is not absence of a fault, and the cleanest fix is not to offer tools that cannot answer.
KERNEL_ONLY_TOOLS = ("ctf_timespan", "ctf_timeline", "query_ctf", "submit_diagnosis")


def _tool_defs(rank_k: int = 0, only_submit: bool = False, kernel_only: bool = False):
    """Tool schemas. rank_k>0 adds the ranked `alternatives` field; only_submit drops the
    query tools (the no-tools baseline); kernel_only keeps just the raw-trace tools."""
    defs = [dict(t) for t in _TOOL_DEFS]
    if kernel_only:
        defs = [t for t in defs if t["name"] in KERNEL_ONLY_TOOLS]
    if rank_k > 0:
        for t in defs:
            if t["name"] == "submit_diagnosis":
                props = dict(t["parameters"]["properties"])
                alt = dict(_ALTERNATIVES_PROP)
                alt["maxItems"] = max(0, rank_k - 1)
                props["alternatives"] = alt
                t["parameters"] = {**t["parameters"], "properties": props}
    if only_submit:
        defs = [t for t in defs if t["name"] == "submit_diagnosis"]
    return defs


def _unmask_diagnosis(diagnosis, guard, tr=None):
    """Bring a submitted verdict back to real names — primary AND ranked alternatives."""
    if diagnosis is None or not config.MASK_NAMES:
        return diagnosis
    submitted = json.loads(json.dumps(diagnosis, default=str))
    diagnosis["root_cause_service"] = guard.unmask(diagnosis.get("root_cause_service"))
    diagnosis["evidence"] = guard.unmask_text(diagnosis.get("evidence"))
    for alt in (diagnosis.get("alternatives") or []):
        if isinstance(alt, dict):
            alt["service"] = guard.unmask(alt.get("service"))
            alt["evidence"] = guard.unmask_text(alt.get("evidence"))
    if tr is not None and submitted != diagnosis:
        tr.event("unmask", submitted=submitted, unmasked=diagnosis, mapping=guard.mapping())
    return diagnosis


def _ranked_from(diagnosis: dict, rank_k: int):
    """Evidence-ranked candidate list: primary first, then alternatives that carry their own
    evidence. Duplicates and unsupported entries are dropped."""
    if not diagnosis:
        return None
    out, seen = [], set()
    for svc, fault in [(diagnosis.get("root_cause_service"), diagnosis.get("fault_type"))] + [
            (a.get("service"), a.get("fault_type"))
            for a in (diagnosis.get("alternatives") or [])
            if isinstance(a, dict) and str(a.get("evidence", "")).strip()]:
        key = str(svc or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"service": svc, "fault_type": fault})
        if rank_k and len(out) >= rank_k:
            break
    return out or None


# transient provider failures worth retrying: rate limits, 5xx, timeouts, and the Azure/OpenAI
# reasoning-model "invalid_prompt" policy flag (fires intermittently on telemetry-heavy turns —
# an identical retry usually passes). Persistent failures still raise → recorded as an error row.
_RETRYABLE = ("429", "rate limit", "rate_limit", "500", "502", "503", "504", "timeout",
              "overloaded", "invalid_prompt")


def _api_call(call, tr, step, tries: int = 4):
    for attempt in range(tries):
        try:
            return call()
        except Exception as e:
            msg = repr(e).lower()
            if attempt == tries - 1 or not any(t in msg for t in _RETRYABLE):
                raise
            tr.event("api_retry", step=step, attempt=attempt + 1, error=repr(e)[:300])
            time.sleep(2 * 2 ** attempt)


def _run_tool(tools: RunTools, name: str, args: dict, guard=None):
    # the model queries in alias space (leakguard) — translate back before touching the data
    svc = args.get("service") or None
    if guard is not None:
        svc = guard.unmask(svc)
    if name == "list_services":
        return {"services": tools.services()}, 0
    if name == "query_traces":
        return tools.traces(svc)
    if name == "query_topology":
        return tools.topology(svc)
    if name == "query_logs":
        return tools.logs(svc)
    if name == "query_metrics":
        return tools.metrics(svc)
    if name == "query_kernel":
        return tools.kernel(svc)
    if name == "query_source":
        return source_tool.query(tools.app, args.get("op", ""), pattern=args.get("pattern"),
                                 path=args.get("path"),
                                 start_line=args.get("start_line") or 1,
                                 limit=args.get("limit") or 120)
    # Raw-trace tools. procname is a kernel comm, not a service alias, so it is NOT unmasked -
    # leakguard aliases services; the trace records the process names the kernel saw.
    if name == "ctf_timespan":
        return ctf_tool.ctf_timespan(tools.run.run_dir), 0
    if name == "ctf_timeline":
        return ctf_tool.ctf_timeline(
            tools.run.run_dir, event=args.get("event") or "",
            buckets=args.get("buckets", 30), procname=args.get("procname")), 0
    if name == "query_ctf":
        return ctf_tool.query_ctf(
            tools.run.run_dir, event=args.get("event") or "",
            begin=args.get("begin"), end=args.get("end"),
            sample=args.get("sample", 10),
            procname=args.get("procname"), contains=args.get("contains")), 0
    return {"error": f"unknown tool {name}"}, 0


def diagnose(run, app: str | None = None, max_steps: int = 14, verbose: bool = False,
             transcript_path: str | None = None, condition: str | None = None,
             meta: dict | None = None, skills: list | None = None,
             inject_brief: bool = False, rank_k: int = 0,
             l0_pack: str | None = None, skill_given: bool = False,
             problem_hint: str | None = None, kernel_only: bool = False) -> dict:
    """Run the agent on one incident. Returns diagnosis + trajectory + usage (no ground-truth here).
    Dispatches on the provider's SDK family — Anthropic vs OpenAI-compatible (azure/gemini/openai/
    ollama) — so the model is a config knob (RCA_PROVIDER/RCA_MODEL); everything else is identical.

    Transcript capture is logging-only (messages and API kwargs are unchanged): every prompt, raw
    API response and full tool result is recorded and, if transcript_path is given, written there —
    including on error, so failed diagnoses are auditable too."""
    tools = RunTools(run, app=app)
    run_id = os.path.basename(run.run_dir)
    # anti-leakage (leakguard.py): the model gets an opaque incident alias, never the run id
    # (run ids literally encode fault/intensity/workload), and fault-revealing container names
    # are pseudonymized in every tool result. The agent answers in alias space; we unmask after.
    guard = leakguard.Guard(enabled=config.MASK_NAMES)
    shown_id = leakguard.alias_run(run_id) if config.MASK_NAMES else run_id
    if kernel_only:
        # Neutral on purpose. The default wording says "Incident 'X'. Services are unknown
        # until you list them" - it asserts that something went wrong, and it points at
        # list_services, which kernel-only mode does not offer. Asserting an incident is a
        # small leak but a real one: it rules out `normal` before the agent has looked.
        user = (f"Kernel trace '{shown_id}' from one host, one recording. Work out whether "
                f"anything went wrong in it and, if so, when, where and why. Then call "
                f"submit_diagnosis.")
    else:
        user = (f"Incident '{shown_id}'. Services are unknown until you list "
                f"them. Diagnose the root cause and call submit_diagnosis.")
    sic = None
    tr = T.Transcript(run_id, method="agent", condition=condition, extra=meta)
    tr.meta["sent_cap_chars"] = SENT_CAP
    tr.meta["max_steps"] = max_steps
    tr.meta["mask_names"] = config.MASK_NAMES
    tr.meta["incident_alias"] = shown_id
    t0 = time.time()
    # ---- v4 skill layer (skills mode only; empty/None library = exactly the frozen v3 path) ----
    # Phase 1: deterministic evidence survey -> masked -> evidence-only skill selection with
    # ABSTAIN. On a match the skill body is appended to the system prompt; on abstain the agent
    # proceeds first-principles. Selection sees ONLY masked evidence — nothing states the problem.
    base_system = SYSTEM_KERNEL_ONLY if kernel_only else SYSTEM
    system_eff, sel = base_system, None
    sel_tokens = {"in": 0, "out": 0}
    survey_bytes = 0
    masked_digest = None
    if skills or inject_brief:
        # Phase 1 runs ONCE; the Shared Investigation Context is the single source both
        # the selector (digest) and the injected brief render from — masked first.
        sic, survey_bytes = context_builder.build_context(tools, run_id)
        masked_digest = guard.mask_obj(sic.digest())
        tr.event("shared_context", **sic.to_jsonable())
    if inject_brief:
        brief = shared_context.format_brief(masked_digest)
        user = (f"Incident '{shown_id}'. Evidence survey (baseline vs incident):\n{brief}\n\n"
                f"This survey already covers the no-filter overview of every tool — do not repeat "
                f"broad survey calls; go directly to targeted per-service and topology queries, "
                f"then call submit_diagnosis.")
    # FAIRNESS: when the comparison gives the blueprint arm the raw kernel trace, the model
    # arms are handed the SAME measurements. The pack contains measurements only - no fault
    # name, no culprit - so it informs without answering.
    if l0_pack and os.path.exists(l0_pack):
        try:
            pk = json.load(open(l0_pack, encoding="utf-8"))
            for k in ("run_id", "family_dir"):
                pk.pop(k, None)
            user += ("\n\nKernel-trace measurements for this incident (from the raw LTTng "
                     "trace, baseline vs incident window):\n"
                     + json.dumps(guard.mask_obj(pk), indent=2, default=str)[:9000])
            tr.event("l0_pack", path=l0_pack, keys=sorted(pk.keys()))
        except Exception as e:                                         # noqa: BLE001
            tr.event("l0_pack_error", error=repr(e))

    # QUESTION 2 (Naser, 16 Sept): "we can assume that they're giving the blueprint along with
    # the problem." Selection is parked, so when exactly one skill is HANDED OVER we bypass the
    # selector entirely. This matters because the old with/without experiment let the agent
    # choose, got the choice right only 19 times in 57, and every regression it measured came
    # from a blueprint written for a different fault - see RESULTS-withwithout.md.
    if skills and skill_given:
        if len(skills) != 1:
            raise ValueError("skill_given expects exactly one blueprint, got %d" % len(skills))
        sk = skills[0]
        system_eff = (base_system +
                      "\n\nBLUEPRINT FOR THIS PROBLEM (given to you; it was not inferred from "
                      f"the evidence): {sk.name}\n"
                      "Follow its method. Still VERIFY its problem signature with your own tool "
                      "queries - if a discriminating check FAILS, say so explicitly rather than "
                      "forcing the blueprint's conclusion onto contradicting evidence.\n"
                      f"{sk.body}")
        tr.event("skill_injected", skill_name=sk.name, body=sk.body, given=True)
        tr.meta["skill_given"] = sk.name
        sel = {"skill_name": sk.name, "skill": sk}
    elif skills:
        evidence_json = json.dumps(masked_digest, default=str)
        tr.event("survey", result=sic.digest(), sent=evidence_json, result_bytes=survey_bytes)
        try:
            sel = _api_call(lambda: skillreg.select(evidence_json, skills), tr, step=-1)
        except Exception as e:
            tr.event("skill_selection", error=repr(e), skill_name="none",
                     note="selector failed -> first-principles fallback")
            sel = None
        if sel:
            sel_tokens = sel.get("tokens") or sel_tokens
            tr.event("skill_selection", skill_name=sel["skill_name"],
                     runner_up=sel.get("runner_up"),
                     confidence=sel.get("confidence"), reason=sel.get("reason"),
                     evidence_sent=evidence_json,
                     skills_shown=[{"name": s.name, "signature": s.signature,
                                    "boundaries": s.boundaries} for s in skills],
                     tokens=sel_tokens)
            if sel.get("skill") is not None:
                sk = sel["skill"]
                system_eff = (base_system +
                              "\n\nACTIVE SKILL (matched by evidence, possibly wrongly): "
                              f"{sk.name}\n"
                              "Before following its blueprint, VERIFY its problem signature with "
                              "your own tool queries — especially the discriminating checks in its "
                              "resolution template. If any discriminating check FAILS, state that "
                              "explicitly and revert to the general method above; never force the "
                              "skill's conclusion onto contradicting evidence.\n"
                              f"{sk.body}")
                tr.event("skill_injected", skill_name=sk.name, body=sk.body)
    # The "hint" half of Naser's ask: "We can test both of them. In the second question, we will
    # tell it, hey, this is the problem." The hint states the SYMPTOM, never the fault name or
    # the culprit service - otherwise it would hand over the answer and the arms stop comparing
    # anything. Same string in both arms, so it cannot advantage one of them.
    if problem_hint:
        user += ("\n\nWhat the operator reports: " + problem_hint +
                 "\nThat is a symptom, not a diagnosis. Confirm or reject it from the evidence.")
        tr.meta["problem_hint"] = problem_hint

    tr.meta["skill_mode"] = bool(skills)
    tr.meta["brief_injected"] = inject_brief
    tr.meta["l0_pack"] = l0_pack or None
    tr.meta["skill_selected"] = sel["skill_name"] if sel else None
    tr.event("system_prompt", text=system_eff, sha256=T.sha256_text(system_eff))
    tr.event("tools_schema", tools=_tool_defs(rank_k, kernel_only=kernel_only))
    tr.meta["kernel_only"] = kernel_only
    tr.event("user_message", text=user)
    loop = _loop_anthropic if config.sdk_kind() == "anthropic" else _loop_openai
    try:
        diagnosis, traj, in_tok, out_tok, bytes_touched = loop(tools, user, max_steps, verbose, tr,
                                                              guard, system_eff, rank_k,
                                                              kernel_only)
    except Exception as e:
        tr.event("error", error=repr(e))
        tr.finalize(None, "error", wall_s=round(time.time() - t0, 1))
        if transcript_path:
            tr.write(transcript_path)
        raise
    diagnosis = _unmask_diagnosis(diagnosis, guard, tr)
    stop = ("submitted" if diagnosis is not None
            else "max_steps" if tr.count("api_response") >= max_steps else "no_tool_calls")
    out = {
        "run_id": run_id,
        "diagnosis": diagnosis,                       # {root_cause_service, fault_type, evidence, confidence} or None
        "ranked_services": [c["service"] for c in (_ranked_from(diagnosis, rank_k) or [])] or None,
        "ranked_candidates": _ranked_from(diagnosis, rank_k),   # (service, fault_type) pairs, evidence-ranked
        "trajectory": traj,                           # RQ2
        "n_tool_calls": len([x for x in traj if x["tool"] != "submit_diagnosis"]),
        "bytes_touched": bytes_touched + survey_bytes,  # RQ4 cost (survey included in skills mode)
        "tokens": {"in": in_tok + sel_tokens["in"], "out": out_tok + sel_tokens["out"]},
        "model": config.model_id(), "wall_s": round(time.time() - t0, 1),
        "transcript_file": transcript_path,
        "skill_selected": (sel or {}).get("skill_name"),
        "skill_confidence": (sel or {}).get("confidence"),
        "brief_injected": inject_brief,
        "n_claims": len(sic) if sic is not None else None,
    }
    tr.finalize(diagnosis, stop, tokens={"in": in_tok, "out": out_tok},
                bytes_touched=bytes_touched, n_tool_calls=out["n_tool_calls"],
                wall_s=out["wall_s"])
    if transcript_path:
        tr.write(transcript_path)
    return out


def diagnose_oneshot(run, app: str | None = None, transcript_path: str | None = None,
                     condition: str | None = None, meta: dict | None = None,
                     rank_k: int = 0, raw_dump: bool = False,
                     l0_pack: str | None = None, **_ignored) -> dict:
    """Model-only baseline: the SAME model, no tool loop, one call.

    Isolates the question "is the result the agent loop, or just the model?". The model sees
    only the deterministic evidence briefing (identical to what the agent is given, same
    masking) and must answer in the same schema. It cannot ask follow-up questions, so any
    gap against the full agent is attributable to iterative investigation rather than to the
    model or to the briefing.

    `raw_dump=True` swaps the briefing for a plain dump of the same survey — the cruder lower
    bound ("just paste telemetry at it").
    """
    t0 = time.time()
    tools = RunTools(run, app=app)
    run_id = os.path.basename(run.run_dir)
    guard = leakguard.Guard(enabled=config.MASK_NAMES)
    shown_id = leakguard.alias_run(run_id) if config.MASK_NAMES else run_id

    method = "llmonly-raw" if raw_dump else "llmonly"
    tr = T.Transcript(run_id, method=method, condition=condition or method, extra=meta)
    tr.meta["mask_names"] = config.MASK_NAMES
    tr.meta["incident_alias"] = shown_id

    sic, survey_bytes = context_builder.build_context(tools, run_id)
    masked_digest = guard.mask_obj(sic.digest())
    tr.event("shared_context", **sic.to_jsonable())
    body = (json.dumps(masked_digest, indent=2, default=str) if raw_dump
            else shared_context.format_brief(masked_digest))

    user = (f"Incident '{shown_id}'. You have NO investigation tools — this is the complete "
            f"evidence available, a baseline-vs-incident survey of every telemetry source:\n\n"
            f"{body}\n\n"
            f"Decide the root cause from this alone and call submit_diagnosis. If the evidence "
            f"is ambiguous, still commit to the best-supported verdict and say why in evidence.")
    if l0_pack and os.path.exists(l0_pack):
        try:
            pk = json.load(open(l0_pack, encoding="utf-8"))
            for k in ("run_id", "family_dir"):
                pk.pop(k, None)
            user += ("\n\nKernel-trace measurements (raw LTTng trace, baseline vs incident):\n"
                     + json.dumps(guard.mask_obj(pk), indent=2, default=str)[:9000])
        except Exception:                                              # noqa: BLE001
            pass
    tr.event("user_message", text=user)

    defs = _tool_defs(rank_k, only_submit=True)
    tr.event("tools_schema", tools=defs)
    diagnosis, itok, otok = None, 0, 0
    try:
        client = config.make_client()
        tc = time.time()
        if config.sdk_kind() == "anthropic":
            schema = [{"name": t["name"], "description": t["description"],
                       "input_schema": t["parameters"]} for t in defs]
            r = _api_call(lambda: client.messages.create(
                model=config.model_id(), max_tokens=config.MAX_TOKENS,
                temperature=config.TEMPERATURE, system=SYSTEM, messages=[{"role": "user", "content": user}],
                tools=schema, tool_choice={"type": "tool", "name": "submit_diagnosis"}), tr, 0)
            tr.event("api_response", step=0, latency_ms=int((time.time() - tc) * 1000),
                     response=T.to_jsonable(r))
            itok, otok = r.usage.input_tokens, r.usage.output_tokens
            tu = next((b for b in r.content if b.type == "tool_use"), None)
            if tu is not None:
                diagnosis = _unmask_diagnosis(dict(tu.input), guard, tr)
        else:
            schema = [{"type": "function", "function": t} for t in defs]
            r = _api_call(lambda: client.chat.completions.create(
                model=config.model_id(),
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                tools=schema,
                tool_choice={"type": "function", "function": {"name": "submit_diagnosis"}},
                **config.openai_create_kwargs()), tr, 0)
            tr.event("api_response", step=0, latency_ms=int((time.time() - tc) * 1000),
                     response=T.to_jsonable(r))
            u = r.usage
            itok, otok = getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)
            m = r.choices[0].message
            if m.tool_calls:
                diagnosis = _unmask_diagnosis(
                    json.loads(m.tool_calls[0].function.arguments), guard, tr)
    except Exception as e:                                              # noqa: BLE001
        tr.event("error", error=repr(e))
        tr.finalize(None, "error", wall_s=round(time.time() - t0, 1))
        if transcript_path:
            tr.write(transcript_path)
        raise

    out = {
        "run_id": run_id, "diagnosis": diagnosis,
        "ranked_services": [c["service"] for c in (_ranked_from(diagnosis, rank_k) or [])] or None,
        "ranked_candidates": _ranked_from(diagnosis, rank_k),
        "trajectory": [], "n_tool_calls": 0,
        "bytes_touched": survey_bytes,
        "tokens": {"in": itok, "out": otok},
        "model": config.model_id(), "wall_s": round(time.time() - t0, 1),
        "transcript_file": transcript_path,
        "skill_selected": None, "skill_confidence": None,
        "brief_injected": not raw_dump, "n_claims": len(sic),
    }
    tr.finalize(diagnosis, "submitted" if diagnosis else "no_tool_calls",
                tokens={"in": itok, "out": otok}, bytes_touched=survey_bytes,
                n_tool_calls=0, wall_s=out["wall_s"])
    if transcript_path:
        tr.write(transcript_path)
    return out


# A model that stops calling tools and just writes prose has NOT answered: the contract is the
# submit_diagnosis call. The first tools-only pilot spent 524 s and 94k tokens finding
# stress-ng-cpu at the right moment, then ended its turn with plain text - and the harness threw
# all of it away as `diagnosis: None`. That is a scored failure caused by the harness, not by the
# agent. So prompt it back, twice, before giving up.
MAX_NUDGES = 2
NUDGE = ("You ended your turn without calling submit_diagnosis, so nothing has been recorded. "
         "Call submit_diagnosis now with your best answer from the evidence you already have. "
         "If the evidence is weak, say so in `confidence` and `evidence` - an honest low-"
         "confidence answer counts, silence does not.")

def _loop_anthropic(tools, user, max_steps, verbose, tr, guard, system=SYSTEM, rank_k=0,
                    kernel_only=False):
    client = config.make_client()
    schema = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
              for t in _tool_defs(rank_k, kernel_only=kernel_only)]
    messages = [{"role": "user", "content": user}]
    traj, itok, otok, bt, diagnosis = [], 0, 0, 0, None
    nudges = 0
    for step in range(max_steps):
        tc = time.time()
        r = _api_call(lambda: client.messages.create(
            model=config.model_id(), max_tokens=config.MAX_TOKENS,
            temperature=config.TEMPERATURE, system=system,
            messages=messages, tools=schema), tr, step)
        tr.event("api_response", step=step, latency_ms=int((time.time() - tc) * 1000),
                 response=T.to_jsonable(r))
        itok += r.usage.input_tokens; otok += r.usage.output_tokens
        messages.append({"role": "assistant", "content": r.content})
        tool_uses = [b for b in r.content if b.type == "tool_use"]
        if not tool_uses:
            if diagnosis is None and nudges < MAX_NUDGES:
                nudges += 1
                tr.event("nudge", step=step, n=nudges)
                messages.append({"role": "user", "content": NUDGE})
                continue
            break
        results = []
        for tu in tool_uses:
            if tu.name == "submit_diagnosis":
                diagnosis = dict(tu.input)
                traj.append({"step": step, "tool": "submit_diagnosis", "service": None})
                tr.event("tool_execution", step=step, tool_use_id=tu.id, tool="submit_diagnosis",
                         arguments=diagnosis, sent="recorded")
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "recorded"})
                continue
            res, b = _run_tool(tools, tu.name, dict(tu.input), guard); bt += b
            svc_real = guard.unmask(tu.input.get("service"))
            traj.append({"step": step, "tool": tu.name, "service": svc_real, "result_bytes": b})
            if verbose:
                print(f"  [{step}] {tu.name}({svc_real or ''}) -> {b}B")
            full = json.dumps(guard.mask_obj(res), default=str)
            sent = full[:SENT_CAP]
            tr.event("tool_execution", step=step, tool_use_id=tu.id, tool=tu.name,
                     arguments=dict(tu.input), result=res, result_bytes=b,
                     sent=sent, truncated=len(full) > SENT_CAP)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": sent})
        messages.append({"role": "user", "content": results})
        if diagnosis is not None:
            break
    return diagnosis, traj, itok, otok, bt


def _loop_openai(tools, user, max_steps, verbose, tr, guard, system=SYSTEM, rank_k=0,
                 kernel_only=False):
    """OpenAI-compatible tool-use loop (Azure / Gemini / OpenAI / Ollama)."""
    client = config.make_client()
    schema = [{"type": "function", "function": t}
              for t in _tool_defs(rank_k, kernel_only=kernel_only)]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ck = config.openai_create_kwargs()
    traj, itok, otok, bt, diagnosis = [], 0, 0, 0, None
    nudges = 0
    for step in range(max_steps):
        tc = time.time()
        r = _api_call(lambda: client.chat.completions.create(
            model=config.model_id(), messages=messages, tools=schema, **ck), tr, step)
        tr.event("api_response", step=step, latency_ms=int((time.time() - tc) * 1000),
                 response=T.to_jsonable(r))
        u = r.usage
        itok += getattr(u, "prompt_tokens", 0); otok += getattr(u, "completion_tokens", 0)
        m = r.choices[0].message
        asst = {"role": "assistant", "content": m.content or ""}
        if m.tool_calls:
            asst["tool_calls"] = [{"id": c.id, "type": "function",
                                   "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                  for c in m.tool_calls]
        messages.append(asst)
        if not m.tool_calls:
            if diagnosis is None and nudges < MAX_NUDGES:
                nudges += 1
                tr.event("nudge", step=step, n=nudges)
                messages.append({"role": "user", "content": NUDGE})
                continue
            break
        for c in m.tool_calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except Exception:
                args = {}
            if name == "submit_diagnosis":
                diagnosis = args
                traj.append({"step": step, "tool": "submit_diagnosis", "service": None})
                tr.event("tool_execution", step=step, tool_use_id=c.id, tool="submit_diagnosis",
                         arguments=args, raw_arguments=c.function.arguments, sent="recorded")
                messages.append({"role": "tool", "tool_call_id": c.id, "content": "recorded"})
                continue
            res, b = _run_tool(tools, name, args, guard); bt += b
            svc_real = guard.unmask(args.get("service"))
            traj.append({"step": step, "tool": name, "service": svc_real, "result_bytes": b})
            if verbose:
                print(f"  [{step}] {name}({svc_real or ''}) -> {b}B")
            full = json.dumps(guard.mask_obj(res), default=str)
            sent = full[:SENT_CAP]
            tr.event("tool_execution", step=step, tool_use_id=c.id, tool=name,
                     arguments=args, raw_arguments=c.function.arguments, result=res, result_bytes=b,
                     sent=sent, truncated=len(full) > SENT_CAP)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": sent})
        if diagnosis is not None:
            break
    return diagnosis, traj, itok, otok, bt


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from stratatrace import load_run
    rd = sys.argv[1]
    app = os.environ.get("STRATATRACE_APP")
    tpath = os.environ.get("RCA_TRANSCRIPT",
                           os.path.join("transcripts", "adhoc", os.path.basename(rd.rstrip('/')) + ".json"))
    out = diagnose(load_run(rd), app=app, verbose=True, transcript_path=tpath)
    gt = load_run(rd).ground_truth.get("fault", {})
    print(json.dumps(out, indent=2, default=str))
    print("\nGROUND TRUTH:", gt.get("target_service"), "/", gt.get("name"), "/", gt.get("family"))
