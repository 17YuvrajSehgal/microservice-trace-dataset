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
                   checked,
                   _api_call, _fit_result, _run_tool, _tool_defs, _unmask_diagnosis,
                   _KO_HEAD, _FAULT_VOCAB, _KO_RULES)

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

# Set to abort an in-flight run. Checked before every model call, which is the only place a
# run spends real time, so a cancel lands within one API round trip rather than at the end of
# the graph. Cleared by diagnose() on entry, so a previous cancel cannot kill the next run.
CANCEL = threading.Event()


class Cancelled(RuntimeError):
    pass


MAX_ROUNDS = 2          # planner rounds; a second one only if the reviewer asks
# Raised from 12 after measuring 554 workers. The distribution of steps used was roughly
# flat from 7 to 11 (53, 48, 46, 54, 42 workers) and then spiked to 280 at exactly 12 -
# that is a wall, not a natural stopping point. 51% of workers were hitting it.
#
# This costs nothing for the half that conclude early: a worker that is done stops, and
# never touches the extra room. It is only spent by the workers that were being cut off,
# and those recorded a median of 1 finding against 2 for workers that finished.
#
# Affordable because the context window is nowhere near full - the worst single call in
# 120 runs used 63k of 400k tokens, 15.7%.
MAX_WORKER_STEPS = 18   # tool-calling turns inside one worker
MAX_SUBTASKS = 4


# --------------------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------------------
class S(TypedDict, total=False):
    run_id: str
    shown_id: str
    plan: list
    findings: Annotated[list, operator.add]   # the scratchpad; workers append concurrently
    # What the workers COMPUTED, as opposed to what they chose to claim. Captured
    # automatically from every run_python call so that a result cannot be lost by a worker
    # moving on without writing it down - which is exactly how the dependency_outage answer
    # was lost on 29-09.
    computed: Annotated[list, operator.add]
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
        self.computed = []

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
    if CANCEL.is_set():
        raise Cancelled("run cancelled")
    client = config.make_client()
    kw = dict(config.openai_create_kwargs())
    schema = [{"type": "function", "function": t} for t in tools]
    if schema:
        kw["tools"] = schema          # tools=[] is rejected by some providers; omit instead
    if force:
        kw["tool_choice"] = {"type": "function", "function": {"name": force}}
    t0 = time.time()
    # checked() raises when the provider returns 200 with an error body - OpenRouter does that
    # for rate limits - so _api_call's retry can see it. Without it the SDK hands back an object
    # whose .choices is None and the next line dies with a TypeError that says nothing.
    r = _api_call(lambda: checked(client.chat.completions.create(
        model=config.model_id(), messages=messages, **kw)), CTX.tr, step)
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
        # Capture it for the synthesiser too. The full snippet is already in the transcript;
        # this is the short version that travels with the run.
        out = (res.get("stdout") or "").strip()
        if out or res.get("error"):
            CTX.computed.append({
                "node": node,
                "why": (args.get("why") or "")[:160],
                "output": out[:COMPUTED_OUT_CAP],
                "truncated": len(out) > COMPUTED_OUT_CAP,
                "error": (res.get("error") or "")[:160] or None,
            })
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


# Chars of tool output kept verbatim in one worker's thread. This one is NOT sized for
# generosity: a thread is re-sent on every step, so its cost grows with the square of the turns,
# and raising it was measured to take a run from 303k tokens to 545k. It is safe to trim here
# precisely because run_python output is captured separately and reaches the synthesiser whole -
# nothing is lost, only re-sent less often. Measured: 0 threads had anything elided in either
# test run at this budget.
# Raised from 80,000. Measured: threads reach 143,632 chars before trimming, so the old
# budget was discarding real content on the longest steps. Trimming only fires on 4% of
# steps, so this changes almost nothing for a typical worker and stops the longest ones
# losing what they gathered. With more steps allowed, threads get longer, so the two
# changes belong together.
THREAD_BUDGET = 150000
# How much of each run_python output travels to the synthesiser. Enough for a ranking table -
# the thing that was lost was a 3-row table - without carrying whole dumps.
# Measured: the 1,600 cap cut 25 of 47 computations, and the 24,000 total dropped more than
# half of what the workers produced - 57,852 chars in one run. Both are now set so that a real
# run carries everything. Uncapped the synthesiser prompt reaches about 22k tokens, which is
# 5.5% of the window; these are a backstop against a pathological run, not a routine trim.
COMPUTED_OUT_CAP = 12000     # matches the largest run_python result measured
COMPUTED_TOTAL_CAP = 240000  # about 60k tokens; observed worst case was 58k chars


def _trim_thread(msgs, node=None, step=None):
    """Keep the most recent tool output verbatim and stub what came before it.

    A tool-calling thread re-sends everything before it on every step, so cost grows with the
    square of the number of steps. Measured on the first full v2 run: one worker that used all
    12 steps spent 322k of the run's 545k prompt tokens on its own, its per-call thread having
    grown to 44k. A single ctf_proclife result is about 11k tokens and was re-sent nine times.

    Stubbing rather than deleting, because the API requires every tool_call to still have its
    matching tool message. And it is safe to stub precisely because the worker records what
    matters through note_finding as it goes: the scratchpad is what reaches the synthesiser,
    not this thread. The stub names the tool and the step so the model can call it again if it
    genuinely needs the detail back.
    """
    idx = [i for i, m in enumerate(msgs) if m.get("role") == "tool"]
    spent = 0
    keep = set()
    for i in reversed(idx):
        c = msgs[i].get("content") or ""
        if spent + len(c) > THREAD_BUDGET and keep:
            break
        spent += len(c)
        keep.add(i)
    out, elided = [], []
    for i, m in enumerate(msgs):
        if m.get("role") == "tool" and i not in keep and len(m.get("content") or "") > 400:
            elided.append({"index": i, "chars": len(msgs[i]["content"])})
            m = dict(m)
            m["content"] = ("[earlier result elided to keep this thread small - %d characters. "
                            "Your note_finding entries are kept in full. Call the tool again if "
                            "you need the detail back.]" % len(msgs[i]["content"]))
        out.append(m)
    # Record the SHAPE of every step and exactly what trimming removed. The thread itself is not
    # stored - it is reconstructable from api_response plus tool_execution, both of which carry
    # node and step, and storing it per step would be quadratic. What could not be reconstructed
    # is what was dropped, so that is what goes in.
    if CTX is not None:
        CTX.event("thread_step", node=node, step=step,
                  messages=len(msgs), tool_messages=len(idx),
                  chars_sent=sum(len(m.get("content") or "") for m in out
                                 if isinstance(m.get("content"), str)),
                  chars_before_trim=sum(len(m.get("content") or "") for m in msgs
                                        if isinstance(m.get("content"), str)),
                  elided=elided, budget=THREAD_BUDGET)
    return out


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
    return [Send("n_work", {"_task": t, "_i": i, "_round": 1})
            for i, t in enumerate(state["plan"])]


def n_work(payload: dict) -> dict:
    task, i, rnd = payload["_task"], payload["_i"], payload["_round"]
    node = "worker%d.%d" % (rnd, i)
    tools = _worker_tools()
    msgs = [{"role": "system", "content": _WORKER},
            {"role": "user", "content":
             "YOUR SUBTASK: %s\n\n%s\n\nRecord findings with note_finding as you go."
             % (task.get("title", "?"), task.get("instruction", ""))}]
    CTX.event("worker_start", node=node, task=task)
    # The planner's and synthesiser's prompts are recorded; a worker's were not, which is where
    # the cost and all the tool use happen. The system prompt is identical across workers but
    # recorded per worker anyway - it differs between the given and none arms, and a reader
    # should not have to know that to trust what they are looking at.
    CTX.event("worker_prompt", node=node, system=msgs[0]["content"], user=msgs[1]["content"],
              tools=[t["name"] for t in tools])
    found, calls = [], 0
    nudged = False
    concluded = False
    for step in range(MAX_WORKER_STEPS):
        m = _call(_trim_thread(msgs, node, step), tools, node, step)
        a = {"role": "assistant", "content": m.content or ""}
        if m.tool_calls:
            a["tool_calls"] = [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name,
                                             "arguments": c.function.arguments}}
                               for c in m.tool_calls]
        msgs.append(a)
        if not m.tool_calls:
            # A worker that recorded nothing has told the synthesiser nothing, and silence
            # reads identically to "checked and found nothing". Ask once.
            if not found and not nudged:
                nudged = True
                CTX.event("worker_nudge", node=node, step=step)
                msgs.append({"role": "user", "content":
                             "You have not recorded a single finding, so nothing you did "
                             "reaches the synthesiser - it cannot see your tool output, only "
                             "what you write with note_finding. Record what you found, AND "
                             "record what you checked and ruled out, with the numbers. If your "
                             "subtask genuinely produced nothing, say that as a finding with "
                             "ruled_out=true rather than leaving it blank."})
                continue
            concluded = True
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
    # MEASURED on the first two campaigns: 234 of 554 workers ran out of steps with tool calls
    # still pending, and 98 of those had recorded NOTHING - a whole investigation that never
    # reached the synthesiser, because only note_finding does. Workers that concluded on their
    # own recorded a median of 2 findings and none recorded zero.
    #
    # Raising MAX_WORKER_STEPS would cost a step on every worker. This costs ONE call, and only
    # on the workers that were about to be dropped silently. Same reasoning as the nudge above:
    # silence from a worker reads identically to "checked and found nothing".
    if not concluded:
        CTX.event("worker_out_of_steps", node=node, findings_so_far=len(found))
        msgs.append({"role": "user", "content":
                     "You are out of steps. Do not call any more query tools - there is no "
                     "turn left to read their output. Record what you have ALREADY seen using "
                     "note_finding, with the numbers you measured. Only note_finding reaches "
                     "the synthesiser; anything you do not record is lost. If you checked "
                     "something and it came to nothing, record that too with ruled_out=true."})
        try:
            m = _call(_trim_thread(msgs, node, MAX_WORKER_STEPS),
                      [t for t in tools if t["name"] == "note_finding"],
                      node, MAX_WORKER_STEPS)
            for c in (m.tool_calls or []):
                if c.function.name != "note_finding":
                    continue
                try:
                    args = json.loads(c.function.arguments or "{}")
                except Exception:                                       # noqa: BLE001
                    continue
                args["_from"] = node
                args["_late"] = True          # recorded in the wrap-up, not during the work
                found.append(args)
                CTX.event("finding", node=node, step=MAX_WORKER_STEPS, finding=args)
        except Exception as e:                                          # noqa: BLE001
            # a failed wrap-up must not lose the findings the worker already has
            CTX.event("worker_wrapup_failed", node=node, error=repr(e)[:200])

    CTX.event("worker_end", node=node, n_findings=len(found), n_tool_calls=calls,
              ran_out_of_steps=not concluded,
              steps_used=step + 1, max_steps=MAX_WORKER_STEPS,
              final_thread_messages=len(msgs),
              final_thread_chars=sum(len(m.get("content") or "") for m in msgs
                                     if isinstance(m.get("content"), str)))
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
    """Route to the synthesiser, or fan a second round out to fresh workers.

    Returning the STRING "n_work" here was a bug: a plain conditional edge hands the node the
    whole graph state, while n_work expects the per-worker payload that Send carries. Round one
    worked because it arrives through Send; round two crashed with KeyError: '_task', so only
    the cells where the reviewer actually asked for more work failed - 13 of 48, which is
    exactly the kind of partial failure that reads as flakiness rather than a bug.
    """
    again = state.get("again") or []
    if not again:
        return "n_synth"
    # offset the index so round-two workers get their own labels in the transcript
    return [Send("n_work", {"_task": t, "_i": 100 + i, "_round": state.get("round", 2)})
            for i, t in enumerate(again)]


def _computed_block() -> str:
    """What the workers actually computed, newest last, under a total budget.

    The synthesiser has no tools, so anything a worker computed and did not write down used to
    be unreachable. This is the safety net: raw output, not a claim, so the synthesiser can see
    a result even when the worker that produced it drew no conclusion from it - and can notice
    when one worker's claim contradicts another worker's table.
    """
    if not CTX or not CTX.computed:
        return "(no code was run)"
    out, used = [], 0
    for c in CTX.computed:
        blk = "- [%s] %s\n%s%s" % (
            c["node"], c["why"] or "(no reason given)", c["output"],
            "\n  ...output truncated" if c["truncated"] else "")
        if c["error"]:
            blk += "\n  ERROR: %s" % c["error"]
        if used + len(blk) > COMPUTED_TOTAL_CAP:
            out.append("- ...%d further results omitted for length; they are in the transcript"
                       % (len(CTX.computed) - len(out)))
            break
        out.append(blk)
        used += len(blk)
    return "\n".join(out)


def n_synth(state: S) -> dict:
    defs = [t for t in _tool_defs(kernel_only=True) if t["name"] == "submit_diagnosis"]
    msgs = [{"role": "system", "content": _SYNTH},
            {"role": "user", "content":
             "Kernel trace '%s'.\n\nWHAT THE WORKERS RECORDED:\n\n%s\n\n"
             "WHAT THE WORKERS COMPUTED - raw output from the code they ran. A worker may have "
             "computed something and drawn no conclusion from it, or drawn a conclusion that "
             "another worker's numbers contradict. Read these against the findings above and "
             "trust the numbers over the summary:\n\n%s\n\nCall submit_diagnosis."
             % (state["shown_id"], _scratchpad(state), _computed_block())}]
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
    CANCEL.clear()
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
    tr.event("computed", computed=CTX.computed)
    tr.event("code_snippets", snippets=CTX.snippets)
    out = {
        "run_id": run_id, "diagnosis": dx,
        "ranked_services": None, "ranked_candidates": None,
        "trajectory": [{"step": i, "tool": s["node"], "service": None}
                       for i, s in enumerate(stats)],
        "n_tool_calls": n_calls,
        "n_code_snippets": len(CTX.snippets),
        "n_findings": len(final.get("findings") or []),
        "n_computed": len(CTX.computed),
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


# --------------------------------------------------------------------------------------
# Interactive follow-up. After a run has committed to a verdict, a human can ask it
# questions, and it answers with the SAME tools, the same guard discipline and the same
# transcript format as the run itself - so a chat answer is as auditable as a verdict.
#
# This is one tool-calling thread, not the plan/work/review graph: a question is one
# worker's worth of work, and the graph exists to decompose an investigation, which a
# question already is. note_finding is dropped (there is no synthesiser to write to) and
# submit_diagnosis is dropped (the verdict already exists); everything else is identical.
# --------------------------------------------------------------------------------------
MAX_CHAT_STEPS = 10

_CHAT_SYS = (
    "You are the investigator that just analysed a Linux kernel trace of a microservice "
    "incident and committed to a verdict. An operator now asks you follow-up questions.\n"
    "- Answer from evidence. When a question needs data, use your tools - do not answer "
    "from memory of the run alone if a query can check it.\n"
    "- Give numbers, time windows (HH:MM:SS) and pid_ns ids, briefly. Plain text, no markdown "
    "tables.\n"
    "- If the evidence cannot answer the question, say exactly that and what is missing.\n"
    "- Never invent events, processes or values not present in tool output.")


class Chat:
    """A follow-up conversation grounded in a finished run. One instance per run."""

    def __init__(self, run, app=None, skill=None, diagnosis=None, findings=None,
                 computed=None, index_root=None):
        run_id = os.path.basename(run.run_dir.rstrip("/"))
        # enabled=False: the run's verdict was already unmasked for the human, so chat must
        # speak real names too - a masked alias would not match the question being asked.
        guard = leakguard.Guard(enabled=False)
        tr = T.Transcript(run_id, method="agent_v2-chat", condition="chat")
        self.ctx = Ctx(RunTools(run, app=app), guard, tr, run_id, index_root=index_root)
        sysp = _CHAT_SYS
        if skill is not None:
            sysp += "\n\nBLUEPRINT USED IN THE INVESTIGATION:\n" + skill.body
        seed = []
        if diagnosis:
            seed.append("YOUR SUBMITTED VERDICT:\n" + json.dumps(diagnosis, indent=1))
        if findings:
            seed.append("FINDINGS YOUR WORKERS RECORDED:\n" + "\n".join(
                "- [%s] %s" % (f.get("_from", "?"),
                               json.dumps({k: v for k, v in f.items()
                                           if not k.startswith("_")}))
                for f in findings))
        if computed:
            seed.append("RAW OUTPUT OF CODE YOUR WORKERS RAN:\n" + "\n".join(
                "- [%s] %s\n%s" % (c.get("node", "?"), c.get("why") or "",
                                   (c.get("output") or "")[:COMPUTED_OUT_CAP])
                for c in computed)[:COMPUTED_TOTAL_CAP])
        if seed:
            sysp += ("\n\nCONTEXT FROM THE RUN YOU JUST FINISHED:\n\n" + "\n\n".join(seed))
        self.msgs = [{"role": "system", "content": sysp}]
        self.tools = [t for t in _worker_tools() if t["name"] != "note_finding"]
        self.turn = 0
        self.ctx.event("chat_open", system=sysp, tools=[t["name"] for t in self.tools])

    def ask(self, question: str) -> str:
        """Answer one question. Blocking; every model call and tool call is recorded in
        self.ctx.tr as it happens, so a poller watching the transcript sees the work live."""
        global CTX
        CTX = self.ctx           # _call/_exec_tool read the module global, same as the graph
        CANCEL.clear()
        self.turn += 1
        node = "chat%d" % self.turn
        self.ctx.event("chat_question", node=node, text=question)
        self.msgs.append({"role": "user", "content": question})
        for step in range(MAX_CHAT_STEPS):
            m = _call(_trim_thread(self.msgs, node, step), self.tools, node, step)
            a = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                a["tool_calls"] = [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name,
                                                 "arguments": c.function.arguments}}
                                   for c in m.tool_calls]
            self.msgs.append(a)
            if not m.tool_calls:
                self.ctx.event("chat_answer", node=node, text=m.content or "")
                return m.content or ""
            for c in m.tool_calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except Exception:                                       # noqa: BLE001
                    args = {}
                self.msgs.append({"role": "tool", "tool_call_id": c.id,
                                  "content": _exec_tool(c.function.name, args, node, step)})
        # out of steps: one final call with no tools forces a text answer from what it has
        self.msgs.append({"role": "user", "content":
                          "You are out of tool steps. Answer now from what you have seen."})
        m = _call(_trim_thread(self.msgs, node, MAX_CHAT_STEPS), [], node, MAX_CHAT_STEPS)
        self.msgs.append({"role": "assistant", "content": m.content or ""})
        self.ctx.event("chat_answer", node=node, text=m.content or "")
        return m.content or ""

    def close(self):
        self.ctx.sb.close()
