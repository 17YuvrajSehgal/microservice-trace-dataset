#!/usr/bin/env python3
"""Agent v2: a LangGraph plan / work / review / synthesise loop over the kernel trace.

WHAT CHANGED FROM v1 (agent.py), and why each one is here rather than being a nice idea:

  1. run_python (codetool.py). v1 could only ask the questions its six tools expressed. The
     three problems it failed hardest on need aggregations none of them can state: summed
     sched_stat_runtime per container (svc_cpu_cap), a retransmission rate over a window
     (anomaly_net), per-flow grouping (svc_net). Now it writes the aggregation itself.
  2. A SCRATCHPAD. Workers record findings as structured claims. v1 carried everything in one
     message thread and a long investigation lost what it found early.
  3. PLANNER AND WORKERS. One planner splits the investigation, several workers run in
     parallel on their own message threads, a reviewer decides whether to go again. v1 did
     everything in one thread, which made it cheap to stop early.

WHAT DELIBERATELY DID NOT CHANGE, because the study depends on it:

  - the prompt body, the fault vocabulary and the submit_diagnosis contract are imported from
    agent.py rather than rewritten, so v1 and v2 answer the same question in the same words.
  - leakguard masks every tool result, including anything run_python prints.
  - transcript.py records every prompt, every raw API response, every tool result and every
    code snippet. LangGraph orchestrates; it never owns the prompt. That is the whole reason
    the model calls go through config.make_client() and not through a LangChain chat wrapper -
    the audit record is the paper's evidence and must not depend on a library's message
    translation.
  - NOTHING HERE READS ground_truth.json.
"""
from __future__ import annotations
import json, operator, os, sys, threading, time
from typing import Annotated, Any, TypedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import codetool
import leakguard
import transcript as T
from tools import RunTools
from agent import (FAULT_TYPES, KERNEL_ONLY_TOOLS, SENT_CAP, SENT_CAP_BY_TOOL,
                   _api_call, _fit_result, _run_tool, _tool_defs, _unmask_diagnosis,
                   _KO_HEAD, _FAULT_VOCAB, _KO_RULES)

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

MAX_ROUNDS = 2          # planner rounds; a second one only if the reviewer asks
MAX_WORKER_STEPS = 12   # tool-calling turns inside one worker
MAX_SUBTASKS = 4


# --------------------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------------------
class S(TypedDict, total=False):
    run_id: str
    shown_id: str
    plan: list
    findings: Annotated[list, operator.add]   # the scratchpad; workers append concurrently
    round: int
    again: list
    diagnosis: dict | None
    worker_stats: Annotated[list, operator.add]


# --------------------------------------------------------------------------------------
# Prompts.
#
# The investigation METHOD is v1's, word for word - that is deliberate, so v1 and v2 differ in
# capability rather than in advice. But v1's opening paragraph counts the tools, and a prompt
# that miscounts them is not a cosmetic problem. The first v2 smoke run proves it: run_python
# was in the schema for every worker, the planner wrote four subtasks phrased entirely in terms
# of the six older tools, and the agent never once wrote code. The prompt said "six tools" and
# the model believed the prompt over the schema.
#
# So the head is patched in exactly two places - the count, and the enumeration - and the
# capability is introduced after the METHOD rather than inside it, leaving v1's numbered steps
# byte-identical. The asserts fail loudly if that wording ever drifts, because a silent miss
# here reads as "the agent chose not to write code" when it was actually told it could not.
_OLD_COUNT = "through six tools."
_OLD_LAST = ("One shows the raw record: ctf_lines "
             "(real event lines with all their fields, over a narrow range).")
assert _OLD_COUNT in _KO_HEAD and _OLD_LAST in _KO_HEAD, "v1 prompt wording changed"

_V2_HEAD = _KO_HEAD.replace(
    _OLD_COUNT, "through seven tools.").replace(
    _OLD_LAST, _OLD_LAST + " And one computes whatever the other six cannot express: "
    "run_python, which runs Python you write over the WHOLE recording, already loaded as a "
    "pandas DataFrame.")

_V2_CODE = (
    "WRITING CODE. The six fixed tools answer a fixed set of questions. run_python answers the "
    "rest, and several things you will want are only reachable that way:\n"
    "- totals per container over a range - summed sched_stat_runtime is CPU time actually "
    "consumed, which no count of events gives you\n"
    "- rates and ratios, including one series against another, and before against after\n"
    "- anything needing a field parsed out of the raw line: TCP source_port/dest_port/seq, "
    "block sectors, scheduling priorities\n"
    "- correlating two events across every 100 ms bucket at once, rather than eyeballing a "
    "30-bucket chart\n"
    "Reach for it whenever a question is about a QUANTITY rather than a shape. If a check you "
    "need requires a number the fixed tools cannot produce, compute it - do not abandon the "
    "check and do not report a figure you did not measure.\n"
    "\n")

_PLANNER = (
    _V2_HEAD + _V2_CODE +
    "YOU ARE THE PLANNER. You do not investigate. You split the work into %d or fewer "
    "INDEPENDENT subtasks that can run at the same time without waiting on each other, and "
    "hand each to a worker that has the same tools you just read about.\n"
    "\n"
    "Good subtasks are different ANGLES on the recording, not the same sweep repeated. For "
    "example: one worker on who appears and disappears, one on how event rates move across "
    "the whole span, one on per-container resource totals, one on the raw lines for whatever "
    "mechanism looks most likely. Bad subtasks are 'find the problem' three times.\n"
    "\n"
    "Each worker also has run_python, so a subtask may ask for an aggregation none of the "
    "fixed tools express - summed CPU time per container, a rate per flow, a count of "
    "repeated TCP sequence numbers.\n"
    "\n"
    "Do not guess the answer. You have not seen any data yet. Say what to look at and how to "
    "tell a real signal from routine noise.\n"
    "\n"
    "AT LEAST ONE subtask must be phrased as a QUANTITY to compute with run_python - CPU time "
    "per container, a rate before against after, a field parsed out of the raw lines. A plan "
    "written entirely in terms of the six fixed tools throws away the only capability that can "
    "answer a question they cannot state." % MAX_SUBTASKS
)

_WORKER = (
    _V2_HEAD + _FAULT_VOCAB + _V2_CODE +
    "YOU ARE ONE WORKER of several, each given a different part of the same investigation. "
    "Do YOUR part properly rather than rushing to a verdict - another worker is covering the "
    "angle you were not given, and a reviewer will put the pieces together.\n"
    "\n"
    "Record what you find with note_finding, as you find it. A finding is a specific claim "
    "with the numbers behind it: which container, which time range, what changed and by how "
    "much. 'Something looks odd around 13:12' is not a finding. Record what you RULED OUT "
    "too - a checked-and-clean angle stops the reviewer chasing it.\n"
    "\n"
    "run_python is there for anything the fixed tools cannot express. Prefer it over guessing "
    "from counts. Print summaries, not raw rows.\n"
    "\n"
    "When your part is done, stop calling tools and reply with one short paragraph. Do not "
    "call submit_diagnosis - that is the synthesiser's job, not yours.\n"
)

_REVIEWER = (
    "You are reviewing an incident investigation of a kernel trace. Several workers each "
    "covered a different angle and recorded what they found. Your job is to decide whether "
    "the evidence already identifies WHAT went wrong, WHERE and WHEN, or whether one more "
    "round of targeted work would settle it.\n"
    "\n"
    "Ask for another round only if a SPECIFIC question would change the answer, and say what "
    "that question is. Do not ask for another round merely because the evidence is thin - if "
    "the trace does not support a confident answer, that is itself the finding. At most one "
    "further round is available, so spend it on the one thing that matters most.\n"
)

_SYNTH = (
    _V2_HEAD + _FAULT_VOCAB + _KO_RULES + "\n\n"
    "YOU ARE THE SYNTHESISER. The investigation is finished. Below is everything the workers "
    "recorded. Weigh it, resolve disagreements by which claim carries the stronger numbers, "
    "and commit with submit_diagnosis.\n"
    "\n"
    "You did not run the tools yourself, so do not invent evidence that is not in the notes. "
    "If the notes do not support a time range, say 'unknown' for the window rather than "
    "guessing one. An honest low-confidence answer counts; a confident invented one does not.\n"
)

_NOTE_DEF = {
    "name": "note_finding",
    "description": ("Record one finding in the shared scratchpad. Call it as soon as you have "
                    "something specific, not at the end. Findings are the only thing that "
                    "survives to the synthesiser - anything you leave in your own reasoning "
                    "is lost."),
    "parameters": {"type": "object", "properties": {
        "claim": {"type": "string", "description":
                  "what you found, in one or two plain sentences, with the numbers"},
        "where": {"type": "string", "description":
                  "the process, pid_ns/container or 'host' it concerns, or 'unclear'"},
        "when": {"type": "string", "description":
                 "the time range it concerns as HH:MM:SS - HH:MM:SS, or 'whole recording'"},
        "evidence": {"type": "string", "description":
                     "which tool call or snippet, and the decisive numbers"},
        "ruled_out": {"type": "boolean", "description":
                      "true if this records something you CHECKED AND CLEARED"},
        "confidence": {"type": "number", "description": "0..1"}},
        "required": ["claim", "where", "evidence", "confidence"]},
}

_PLAN_DEF = {
    "name": "submit_plan",
    "description": "Hand the subtasks to the workers.",
    "parameters": {"type": "object", "properties": {
        "subtasks": {"type": "array", "maxItems": MAX_SUBTASKS, "items": {
            "type": "object", "properties": {
                "title": {"type": "string", "description": "3-6 words"},
                "instruction": {"type": "string", "description":
                                "what this worker should do, concretely, and what would count "
                                "as a real signal rather than routine noise"}},
            "required": ["title", "instruction"]}}},
        "required": ["subtasks"]},
}

_REVIEW_DEF = {
    "name": "submit_review",
    "description": "Decide whether one more round of work is needed.",
    "parameters": {"type": "object", "properties": {
        "enough": {"type": "boolean", "description":
                   "true if the evidence already answers what, where and when"},
        "gaps": {"type": "string", "description": "what is still open, in one or two sentences"},
        "followups": {"type": "array", "maxItems": 2, "items": {
            "type": "object", "properties": {
                "title": {"type": "string"},
                "instruction": {"type": "string"}},
            "required": ["title", "instruction"]},
            "description": "only if enough is false"}},
        "required": ["enough", "gaps"]},
}


# --------------------------------------------------------------------------------------
# Run-scoped services. One sandbox per run, shared under a lock: loading a 3-million-row
# index takes seconds, and workers run concurrently but each sandbox call is one
# request/response over a pipe, so serialising the calls is both necessary and cheap.
# --------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, tools, guard, tr, run_id, index_root=None):
        self.tools, self.guard, self.tr, self.run_id = tools, guard, tr, run_id
        self.sb = codetool.Sandbox(run_id, index_root=index_root)
        self.sb_lock = threading.Lock()
        self.tr_lock = threading.Lock()
        self.bytes = 0
        self.tok_in = 0
        self.tok_out = 0
        self.snippets = []

    def event(self, kind, **kw):
        with self.tr_lock:
            self.tr.event(kind, **kw)

    def add_tokens(self, r):
        u = getattr(r, "usage", None)
        with self.tr_lock:
            self.tok_in += getattr(u, "prompt_tokens", 0) or 0
            self.tok_out += getattr(u, "completion_tokens", 0) or 0


CTX: Ctx | None = None      # set by diagnose(); the graph nodes read it


def _call(messages, tools, node, step, force=None):
    """One model call. Recorded in the transcript exactly as v1 records it."""
    client = config.make_client()
    kw = dict(config.openai_create_kwargs())
    schema = [{"type": "function", "function": t} for t in tools]
    if force:
        kw["tool_choice"] = {"type": "function", "function": {"name": force}}
    t0 = time.time()
    r = _api_call(lambda: client.chat.completions.create(
        model=config.model_id(), messages=messages, tools=schema, **kw), CTX.tr, step)
    CTX.event("api_response", node=node, step=step,
              latency_ms=int((time.time() - t0) * 1000), response=T.to_jsonable(r))
    CTX.add_tokens(r)
    return r.choices[0].message


def _exec_tool(name, args, node, step):
    """Run one tool and return the masked, size-fitted string the model will see."""
    if name == "run_python":
        with CTX.sb_lock:
            res = CTX.sb.run(args.get("code") or "")
        CTX.snippets.append({"node": node, "code": args.get("code"),
                             "why": args.get("why"), "result": res})
        b = len(json.dumps(res, default=str))
    else:
        res, b = _run_tool(CTX.tools, name, args, CTX.guard)
    CTX.bytes += b
    masked = CTX.guard.mask_obj(res)
    cap = SENT_CAP_BY_TOOL.get(name, SENT_CAP)
    sent, cut, dropped = _fit_result(masked, cap)
    CTX.event("tool_execution", node=node, step=step, tool=name, arguments=args,
              result=res, result_bytes=b, sent=sent, truncated=cut, dropped=dropped,
              sent_cap=cap)
    return sent


def _worker_tools():
    defs = [t for t in _tool_defs(kernel_only=True)
            if t["name"] in KERNEL_ONLY_TOOLS and t["name"] != "submit_diagnosis"]
    return defs + [codetool.TOOL_DEF, _NOTE_DEF]


# --------------------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------------------
def n_plan(state: S) -> dict:
    msgs = [{"role": "system", "content": _PLANNER},
            {"role": "user", "content":
             "Kernel trace '%s' from one host, one recording. Nobody has told you whether "
             "anything went wrong. Split the investigation and call submit_plan."
             % state["shown_id"]}]
    CTX.event("planner_prompt", text=_PLANNER, user=msgs[1]["content"])
    m = _call(msgs, [_PLAN_DEF], "planner", 0, force="submit_plan")
    subs = []
    if m.tool_calls:
        try:
            subs = (json.loads(m.tool_calls[0].function.arguments or "{}") or {}).get(
                "subtasks") or []
        except Exception:                                               # noqa: BLE001
            subs = []
    if not subs:
        # a planner that returns nothing must not silently become a no-op run
        subs = [{"title": "full investigation",
                 "instruction": "Investigate the whole recording on your own judgement."}]
    subs = subs[:MAX_SUBTASKS]
    CTX.event("plan", round=1, subtasks=subs)
    return {"plan": subs, "round": 1}


def _fan(state: S):
    tasks = state.get("again") or state["plan"]
    return [Send("n_work", {"_task": t, "_i": i, "_round": state.get("round", 1)})
            for i, t in enumerate(tasks)]


def n_work(payload: dict) -> dict:
    task, i, rnd = payload["_task"], payload["_i"], payload["_round"]
    node = "worker%d.%d" % (rnd, i)
    tools = _worker_tools()
    msgs = [{"role": "system", "content": _WORKER},
            {"role": "user", "content":
             "YOUR SUBTASK: %s\n\n%s\n\nRecord findings with note_finding as you go."
             % (task.get("title", "?"), task.get("instruction", ""))}]
    CTX.event("worker_start", node=node, task=task)
    found, calls = [], 0
    for step in range(MAX_WORKER_STEPS):
        m = _call(msgs, tools, node, step)
        a = {"role": "assistant", "content": m.content or ""}
        if m.tool_calls:
            a["tool_calls"] = [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name,
                                             "arguments": c.function.arguments}}
                               for c in m.tool_calls]
        msgs.append(a)
        if not m.tool_calls:
            break
        for c in m.tool_calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except Exception:                                           # noqa: BLE001
                args = {}
            if name == "note_finding":
                args["_from"] = node
                found.append(args)
                CTX.event("finding", node=node, step=step, finding=args)
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": "recorded"})
                continue
            calls += 1
            msgs.append({"role": "tool", "tool_call_id": c.id,
                         "content": _exec_tool(name, args, node, step)})
    CTX.event("worker_end", node=node, n_findings=len(found), n_tool_calls=calls)
    return {"findings": found,
            "worker_stats": [{"node": node, "tool_calls": calls, "findings": len(found)}]}


def _scratchpad(state: S) -> str:
    out = []
    for f in state.get("findings") or []:
        out.append("- [%s]%s %s\n    where: %s | when: %s\n    evidence: %s (confidence %s)"
                   % (f.get("_from", "?"), " RULED OUT:" if f.get("ruled_out") else "",
                      f.get("claim", ""), f.get("where", "?"), f.get("when", "?"),
                      f.get("evidence", ""), f.get("confidence")))
    return "\n".join(out) or "(the workers recorded nothing)"


def n_review(state: S) -> dict:
    if state.get("round", 1) >= MAX_ROUNDS:
        CTX.event("review", skipped="round budget spent")
        return {"again": []}
    msgs = [{"role": "system", "content": _REVIEWER},
            {"role": "user", "content": "FINDINGS SO FAR:\n\n" + _scratchpad(state)}]
    m = _call(msgs, [_REVIEW_DEF], "reviewer", 0, force="submit_review")
    rev = {}
    if m.tool_calls:
        try:
            rev = json.loads(m.tool_calls[0].function.arguments or "{}") or {}
        except Exception:                                               # noqa: BLE001
            rev = {}
    CTX.event("review", review=rev)
    if rev.get("enough", True):
        return {"again": []}
    return {"again": (rev.get("followups") or [])[:2], "round": state.get("round", 1) + 1}


def _after_review(state: S):
    return "n_work" if state.get("again") else "n_synth"


def n_synth(state: S) -> dict:
    defs = [t for t in _tool_defs(kernel_only=True) if t["name"] == "submit_diagnosis"]
    msgs = [{"role": "system", "content": _SYNTH},
            {"role": "user", "content":
             "Kernel trace '%s'. Everything the workers recorded:\n\n%s\n\nCall "
             "submit_diagnosis." % (state["shown_id"], _scratchpad(state))}]
    CTX.event("synth_prompt", text=_SYNTH, user=msgs[1]["content"])
    dx = None
    for attempt in range(2):
        m = _call(msgs, defs, "synth", attempt, force="submit_diagnosis")
        if m.tool_calls:
            try:
                dx = json.loads(m.tool_calls[0].function.arguments or "{}")
                break
            except Exception:                                           # noqa: BLE001
                pass
        msgs.append({"role": "user", "content":
                     "You did not produce a usable submit_diagnosis call. Do it now."})
    return {"diagnosis": dx}


def build_graph():
    g = StateGraph(S)
    g.add_node("n_plan", n_plan)
    g.add_node("n_work", n_work)
    g.add_node("n_review", n_review)
    g.add_node("n_synth", n_synth)
    g.add_edge(START, "n_plan")
    g.add_conditional_edges("n_plan", _fan, ["n_work"])
    g.add_edge("n_work", "n_review")
    g.add_conditional_edges("n_review", _after_review, ["n_work", "n_synth"])
    g.add_edge("n_synth", END)
    return g.compile()


# --------------------------------------------------------------------------------------
def diagnose(run, app=None, transcript_path=None, condition=None, meta=None,
             skills=None, skill_given=False, problem_hint=None, index_root=None,
             kernel_only=True, **_ignored) -> dict:
    """Same signature and same return shape as agent.diagnose, so the harness is unchanged."""
    global CTX
    t0 = time.time()
    tools = RunTools(run, app=app)
    run_id = os.path.basename(run.run_dir.rstrip("/"))
    guard = leakguard.Guard(enabled=config.MASK_NAMES)
    shown = leakguard.alias_run(run_id) if config.MASK_NAMES else run_id

    tr = T.Transcript(run_id, method="agent_v2", condition=condition, extra=meta)
    tr.meta.update({"agent": "v2-langgraph", "mask_names": config.MASK_NAMES,
                    "incident_alias": shown, "max_rounds": MAX_ROUNDS,
                    "max_worker_steps": MAX_WORKER_STEPS, "max_subtasks": MAX_SUBTASKS,
                    "sent_cap_chars": SENT_CAP, "sent_cap_by_tool": dict(SENT_CAP_BY_TOOL),
                    "kernel_only": kernel_only})
    CTX = Ctx(tools, guard, tr, run_id, index_root=index_root)

    global _WORKER, _SYNTH
    worker_sys, synth_sys = _WORKER, _SYNTH
    if skills and skill_given:
        if len(skills) != 1:
            raise ValueError("skill_given expects exactly one blueprint, got %d" % len(skills))
        sk = skills[0]
        extra = ("\n\nBLUEPRINT FOR THIS PROBLEM (given to you; it was not inferred from the "
                 "evidence): %s\nFollow its method. Still VERIFY its problem signature with "
                 "your own queries - if a discriminating check FAILS, say so explicitly rather "
                 "than forcing the blueprint's conclusion onto contradicting evidence. If a "
                 "check needs a quantity the fixed tools cannot compute, compute it with "
                 "run_python rather than abstaining.\n%s" % (sk.name, sk.body))
        _WORKER = worker_sys + extra
        _SYNTH = synth_sys + extra
        tr.event("skill_injected", skill_name=sk.name, body=sk.body, given=True)
        tr.meta["skill_given"] = sk.name
    if problem_hint:
        hint = ("\n\nWhat the operator reports: " + problem_hint +
                "\nThat is a symptom, not a diagnosis. Confirm or reject it from the evidence.")
        _WORKER = _WORKER + hint
        _SYNTH = _SYNTH + hint
        tr.meta["problem_hint"] = problem_hint

    try:
        final = build_graph().invoke({"run_id": run_id, "shown_id": shown,
                                      "findings": [], "worker_stats": [], "round": 1},
                                     {"recursion_limit": 60})
        dx = _unmask_diagnosis(final.get("diagnosis"), guard, tr)
    except Exception as e:                                              # noqa: BLE001
        tr.event("error", error=repr(e))
        tr.finalize(None, "error", wall_s=round(time.time() - t0, 1))
        if transcript_path:
            tr.write(transcript_path)
        CTX.sb.close()
        raise
    finally:
        _WORKER, _SYNTH = worker_sys, synth_sys

    stats = final.get("worker_stats") or []
    n_calls = sum(s["tool_calls"] for s in stats)
    tr.event("scratchpad", findings=final.get("findings") or [])
    tr.event("code_snippets", snippets=CTX.snippets)
    out = {
        "run_id": run_id, "diagnosis": dx,
        "ranked_services": None, "ranked_candidates": None,
        "trajectory": [{"step": i, "tool": s["node"], "service": None}
                       for i, s in enumerate(stats)],
        "n_tool_calls": n_calls,
        "n_code_snippets": len(CTX.snippets),
        "n_findings": len(final.get("findings") or []),
        "bytes_touched": CTX.bytes,
        "tokens": {"in": CTX.tok_in, "out": CTX.tok_out},
        "model": config.model_id(), "wall_s": round(time.time() - t0, 1),
        "transcript_file": transcript_path,
        "skill_selected": (skills[0].name if (skills and skill_given) else None),
        "skill_confidence": None, "brief_injected": False, "n_claims": None,
    }
    tr.finalize(dx, "submitted" if dx else "no_diagnosis",
                tokens={"in": CTX.tok_in, "out": CTX.tok_out},
                bytes_touched=CTX.bytes, n_tool_calls=n_calls, wall_s=out["wall_s"])
    if transcript_path:
        tr.write(transcript_path)
    CTX.sb.close()
    return out


if __name__ == "__main__":
    from stratatrace import load_run
    rd = sys.argv[1]
    tp = os.environ.get("RCA_TRANSCRIPT",
                        os.path.join("transcripts", "v2",
                                     os.path.basename(rd.rstrip("/")) + ".json"))
    o = diagnose(load_run(rd), app=os.environ.get("STRATATRACE_APP"), transcript_path=tp)
    print(json.dumps(o, indent=2, default=str))
