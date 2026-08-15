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

SYSTEM = (
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
    "RULES: root_cause_service is the culprit component as named in telemetry — name the "
    "unexplained workload/container itself if a co-tenant is the cause, or 'host' for host-wide "
    "resource causes with no visible culprit workload. Distinguish victims from the culprit. Be "
    "economical with tool calls; never guess before checking baseline->incident evidence."
)

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
    {"name": "submit_diagnosis", "description": "Commit the final root-cause verdict.",
     "parameters": {"type": "object", "properties": {
         "root_cause_service": {"type": "string", "description": "the single culprit service/container"},
         "fault_type": {"type": "string", "enum": FAULT_TYPES},
         "evidence": {"type": "string", "description": "1-3 sentences citing the decisive signals"},
         "confidence": {"type": "number", "description": "0..1"}},
         "required": ["root_cause_service", "fault_type", "evidence", "confidence"]}},
]


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
    return {"error": f"unknown tool {name}"}, 0


def diagnose(run, app: str | None = None, max_steps: int = 14, verbose: bool = False,
             transcript_path: str | None = None, condition: str | None = None,
             meta: dict | None = None, skills: list | None = None,
             inject_brief: bool = False) -> dict:
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
    system_eff, sel = SYSTEM, None
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
                f"Investigate further with the tools and call submit_diagnosis.")
    if skills:
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
                     confidence=sel.get("confidence"), reason=sel.get("reason"),
                     evidence_sent=evidence_json,
                     skills_shown=[{"name": s.name, "signature": s.signature} for s in skills],
                     tokens=sel_tokens)
            if sel.get("skill") is not None:
                sk = sel["skill"]
                system_eff = (SYSTEM +
                              "\n\nACTIVE SKILL (matched by evidence — verify it fits; abandon it "
                              "and use the general method if the evidence contradicts it):\n"
                              f"### {sk.name}\n{sk.body}")
                tr.event("skill_injected", skill_name=sk.name, body=sk.body)
    tr.meta["skill_mode"] = bool(skills)
    tr.meta["brief_injected"] = inject_brief
    tr.meta["skill_selected"] = sel["skill_name"] if sel else None
    tr.event("system_prompt", text=system_eff, sha256=T.sha256_text(system_eff))
    tr.event("tools_schema", tools=_TOOL_DEFS)
    tr.event("user_message", text=user)
    loop = _loop_anthropic if config.sdk_kind() == "anthropic" else _loop_openai
    try:
        diagnosis, traj, in_tok, out_tok, bytes_touched = loop(tools, user, max_steps, verbose, tr,
                                                              guard, system_eff)
    except Exception as e:
        tr.event("error", error=repr(e))
        tr.finalize(None, "error", wall_s=round(time.time() - t0, 1))
        if transcript_path:
            tr.write(transcript_path)
        raise
    if diagnosis is not None and config.MASK_NAMES:
        submitted = dict(diagnosis)
        diagnosis["root_cause_service"] = guard.unmask(diagnosis.get("root_cause_service"))
        diagnosis["evidence"] = guard.unmask_text(diagnosis.get("evidence"))
        if submitted != diagnosis:
            tr.event("unmask", submitted=submitted, unmasked=diagnosis, mapping=guard.mapping())
    stop = ("submitted" if diagnosis is not None
            else "max_steps" if tr.count("api_response") >= max_steps else "no_tool_calls")
    out = {
        "run_id": run_id,
        "diagnosis": diagnosis,                       # {root_cause_service, fault_type, evidence, confidence} or None
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


def _loop_anthropic(tools, user, max_steps, verbose, tr, guard, system=SYSTEM):
    client = config.make_client()
    schema = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
              for t in _TOOL_DEFS]
    messages = [{"role": "user", "content": user}]
    traj, itok, otok, bt, diagnosis = [], 0, 0, 0, None
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


def _loop_openai(tools, user, max_steps, verbose, tr, guard, system=SYSTEM):
    """OpenAI-compatible tool-use loop (Azure / Gemini / OpenAI / Ollama)."""
    client = config.make_client()
    schema = [{"type": "function", "function": t} for t in _TOOL_DEFS]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ck = config.openai_create_kwargs()
    traj, itok, otok, bt, diagnosis = [], 0, 0, 0, None
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
