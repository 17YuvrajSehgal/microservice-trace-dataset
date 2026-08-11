#!/usr/bin/env python3
"""The LLM RCA agent — drives the four telemetry tools to a structured diagnosis.

Given a run (one incident) it exposes the 4 deterministic tools (traces/logs/metrics/kernel) to a
tool-using LLM and lets it investigate freely, then commit to the output contract
    { root_cause_service, fault_type, evidence, confidence }
While it runs it records the **trajectory** (every tool call, target service, result-size, next
tool) + token usage — that is RQ2's dependent variable, and the byte totals feed RQ4's cost axis.

The loop is intentionally provider-native for Anthropic (tool-use requires provider-specific message
threading); model id / temperature / max_tokens come from `config.py` so the model is still a config
knob. (An OpenAI/ollama agent loop is a later extension; the single-turn `config.chat` already is
multi-provider for the statistical/narration paths.)

Degradation note: the agent is HELD FIXED. To study telemetry degradation you pass a degraded Run
(same interface) — the agent code never changes. That keeps Axis A (data) and Axis B (agent) clean.
"""
from __future__ import annotations
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from tools import RunTools

# fault vocabulary the agent must choose from (aligns with ground_truth families for scoring)
FAULT_TYPES = [
    "cpu_saturation", "memory_pressure", "disk_io", "network_latency", "db_latency",
    "dependency_outage", "error_storm", "noisy_neighbor", "cpu_throttling",
    "memory_limit", "service_network", "queue_backlog", "normal",
]

SYSTEM = (
    "You are a senior SRE doing root-cause analysis of a single incident in a microservice system. "
    "An anomaly was detected in a known time window. You have four read-only telemetry tools "
    "(traces, logs, metrics, kernel), each returning compact per-service summaries for that window. "
    "Investigate efficiently: form hypotheses, query the tools to confirm/refute, localize the ONE "
    "root-cause service and the fault type. Distinguish victims (services that merely slow/err "
    "because they depend on the culprit) from the true cause. When confident, call submit_diagnosis. "
    "Be economical with tool calls but do not guess before you have evidence."
)

_TOOL_DEFS = [
    {"name": "list_services", "description": "List the services/containers present in this incident.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "query_traces", "description": "SERVER-span latency (p50/p95/p99/count) per service in the window. Omit service for all.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_logs", "description": "Error counts + top normalized error signatures per container. Omit service for all.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_metrics", "description": "Resource signals (cpu/throttle/mem/net/fs) baseline→injection per container, ranked by movement.",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "query_kernel", "description": "Kernel evidence per service: syscall-latency peaks, L3 deviation digests, L2 wait-attribution (if present).",
     "parameters": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "submit_diagnosis", "description": "Commit the final root-cause verdict.",
     "parameters": {"type": "object", "properties": {
         "root_cause_service": {"type": "string", "description": "the single culprit service/container"},
         "fault_type": {"type": "string", "enum": FAULT_TYPES},
         "evidence": {"type": "string", "description": "1-3 sentences citing the decisive signals"},
         "confidence": {"type": "number", "description": "0..1"}},
         "required": ["root_cause_service", "fault_type", "evidence", "confidence"]}},
]


def _run_tool(tools: RunTools, name: str, args: dict):
    svc = args.get("service") or None
    if name == "list_services":
        return {"services": tools.services()}, 0
    if name == "query_traces":
        return tools.traces(svc)
    if name == "query_logs":
        return tools.logs(svc)
    if name == "query_metrics":
        return tools.metrics(svc)
    if name == "query_kernel":
        return tools.kernel(svc)
    return {"error": f"unknown tool {name}"}, 0


def diagnose(run, app: str | None = None, max_steps: int = 14, verbose: bool = False) -> dict:
    """Run the agent on one incident. Returns diagnosis + trajectory + usage (no ground-truth here).
    Dispatches on the provider's SDK family — Anthropic vs OpenAI-compatible (azure/gemini/openai/
    ollama) — so the model is a config knob (RCA_PROVIDER/RCA_MODEL); everything else is identical."""
    tools = RunTools(run, app=app)
    user = (f"Incident in run '{os.path.basename(run.run_dir)}'. Services are unknown until you list "
            f"them. Diagnose the root cause and call submit_diagnosis.")
    t0 = time.time()
    loop = _loop_anthropic if config.sdk_kind() == "anthropic" else _loop_openai
    diagnosis, traj, in_tok, out_tok, bytes_touched = loop(tools, user, max_steps, verbose)
    return {
        "run_id": os.path.basename(run.run_dir),
        "diagnosis": diagnosis,                       # {root_cause_service, fault_type, evidence, confidence} or None
        "trajectory": traj,                           # RQ2
        "n_tool_calls": len([x for x in traj if x["tool"] != "submit_diagnosis"]),
        "bytes_touched": bytes_touched,               # RQ4 cost
        "tokens": {"in": in_tok, "out": out_tok},     # RQ2/RQ4 cost
        "model": config.model_id(), "wall_s": round(time.time() - t0, 1),
    }


def _loop_anthropic(tools, user, max_steps, verbose):
    client = config.make_client()
    schema = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
              for t in _TOOL_DEFS]
    messages = [{"role": "user", "content": user}]
    traj, itok, otok, bt, diagnosis = [], 0, 0, 0, None
    for step in range(max_steps):
        r = client.messages.create(model=config.model_id(), max_tokens=config.MAX_TOKENS,
                                   temperature=config.TEMPERATURE, system=SYSTEM,
                                   messages=messages, tools=schema)
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
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "recorded"})
                continue
            res, b = _run_tool(tools, tu.name, dict(tu.input)); bt += b
            traj.append({"step": step, "tool": tu.name, "service": tu.input.get("service"), "result_bytes": b})
            if verbose:
                print(f"  [{step}] {tu.name}({tu.input.get('service') or ''}) -> {b}B")
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(res, default=str)[:6000]})
        messages.append({"role": "user", "content": results})
        if diagnosis is not None:
            break
    return diagnosis, traj, itok, otok, bt


def _loop_openai(tools, user, max_steps, verbose):
    """OpenAI-compatible tool-use loop (Azure / Gemini / OpenAI / Ollama)."""
    client = config.make_client()
    schema = [{"type": "function", "function": t} for t in _TOOL_DEFS]
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    ck = config.openai_create_kwargs()
    traj, itok, otok, bt, diagnosis = [], 0, 0, 0, None
    for step in range(max_steps):
        r = client.chat.completions.create(model=config.model_id(), messages=messages, tools=schema, **ck)
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
                messages.append({"role": "tool", "tool_call_id": c.id, "content": "recorded"})
                continue
            res, b = _run_tool(tools, name, args); bt += b
            traj.append({"step": step, "tool": name, "service": args.get("service"), "result_bytes": b})
            if verbose:
                print(f"  [{step}] {name}({args.get('service') or ''}) -> {b}B")
            messages.append({"role": "tool", "tool_call_id": c.id,
                             "content": json.dumps(res, default=str)[:6000]})
        if diagnosis is not None:
            break
    return diagnosis, traj, itok, otok, bt


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from stratatrace import load_run
    rd = sys.argv[1]
    app = os.environ.get("STRATATRACE_APP")
    out = diagnose(load_run(rd), app=app, verbose=True)
    gt = load_run(rd).ground_truth.get("fault", {})
    print(json.dumps(out, indent=2, default=str))
    print("\nGROUND TRUTH:", gt.get("target_service"), "/", gt.get("name"), "/", gt.get("family"))
