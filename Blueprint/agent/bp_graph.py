#!/usr/bin/env python3
"""A blueprint run as a graph: the harness keeps the structure, the agent keeps the judgment.

The blueprint is a `blueprint.yaml` (steps, suggested commands, how to read the output, the
ways a step can end). It is NOT pasted into the prompt as one text. For each step the agent
gets that step's guidance and a short case file, works it with the blueprint's tools, and
closes it with `finish_step`. What the harness enforces:

  - one step at a time, and only that step's tool output is in the context;
  - a step ends with an outcome and the facts it must establish, or the reason it cannot;
  - evidence lines are checked against the real tool output;
  - every time the agent leaves the guidance (another outcome, a jump, a tool the step does
    not suggest) it is allowed, and it is logged with the agent's reason.

So the blueprint guides and the agent decides. The log says how often it followed.

    python bp_graph.py <run_dir> <blueprint.yaml> [--out result.json]
    python bp_graph.py --selftest          # graph logic with a scripted model, no trace, no API

Model: the OpenAI-compatible family through config.py (openai, LM Studio, openrouter, ...).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

import yaml
from langgraph.graph import END, START, StateGraph

OUT_CAP = 8000        # characters of one tool output the model sees
MAX_VISITS = 16       # step visits in one run; stops a back-and-forth between two steps
GRACE = 2             # extra turns after a step's budget before the harness closes it

SYSTEM = """You investigate a Linux kernel trace (LTTng) to confirm or reject ONE root cause:
{confirms}

BACKGROUND
{background}
PROBLEMS THAT LOOK SIMILAR
{lookalikes}
HOW YOU WORK
The investigation follows a blueprint: a method tested on labelled traces. You get one step
at a time. Each step has a goal, suggested commands, and notes on how to read the output.
The blueprint is guidance, not a script. The suggested commands worked on other traces; use
them when they fit this one. When what you see does not fit the guidance, use your own
judgment: other arguments, another tool, more slices, a step back, a step skipped, or an
early stop. When you leave the guidance, say why in finish_step. Being right about this
trace matters more than following the steps.

RULES
- Use run_tool to run the blueprint's scripts. $TRACE is the trace folder, $WORK a scratch
  folder that keeps your slices for the whole investigation.
- Decide from numbers in tool output, by comparing with a normal slice of the same trace.
  Never state something a tool output did not show.
- Closing a step moves the investigation on; it does not end it. A check that belongs to a
  later step is done in that step, not here.
- Close every step with finish_step. Evidence lines must be copied word for word from tool
  output. Only your summary, facts and evidence go on to the next step; the raw output does
  not, so put every value you will need later into facts.

THE STEPS: {step_map}"""


class S(TypedDict, total=False):
    step: str          # the current step id, or "report"
    go: str            # where the graph goes next: enter | think | report
    facts: dict        # the case file: values established so far
    ledger: list       # one entry per finished step visit
    msgs: list         # messages of the current step only
    turns: int         # model turns in the current step
    used: list         # scripts run in the current step
    nudges: int
    rejects: int
    visits: int
    conclusion: str    # set when a stop outcome ends the investigation
    handoff: str       # folder of the blueprint this one hands the case to
    verdict: str       # confirmed | unconfirmed | rejected | inconclusive, from the outcomes reached
    final: dict


def load_env(path):
    """Minimal .env reader (KEY=VALUE, `#` comments). Does not overwrite what is already set."""
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*([A-Za-z_]\w*)=(.*)", line)
            if m:
                os.environ.setdefault(m.group(1), re.sub(r"\s+#.*$", "", m.group(2)).strip())


def openai_llm():
    # ponytail: OpenAI-compatible providers only; add the Anthropic message shape when a
    # Claude run is wanted (agent_v2.py has it).
    import config
    client = config.make_client()

    def call(messages, tools, force=None):
        kw = dict(config.openai_create_kwargs())
        if force:
            kw["tool_choice"] = {"type": "function", "function": {"name": force}}
        r = client.chat.completions.create(
            model=config.model_id(), messages=messages, timeout=300,
            tools=[{"type": "function", "function": t} for t in tools], **kw)
        m = r.choices[0].message
        u = r.usage
        return {"content": m.content or "",
                "tool_calls": [{"id": c.id, "name": c.function.name, "args": c.function.arguments}
                               for c in (m.tool_calls or [])],
                "in": getattr(u, "prompt_tokens", 0) or 0, "out": getattr(u, "completion_tokens", 0) or 0}
    return call


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


class Investigation:
    def __init__(self, spec, runner, llm, hide=(), log=print):
        self.spec, self.runner, self.llm, self.log = spec, runner, llm, log
        self.steps = spec["steps"]
        self.hide = [h for h in hide if h]       # strings the model must not see (run name, paths)
        self.outputs = []                        # every tool output, for the evidence check
        self.step_out = []                       # tool output of the current step, for its verdict line
        self.vars = spec.get("vars") or {}       # named event lists ($MEMSYS), expanded in tool arguments
        self.stats = {"model_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0}
        self.events = []
        g = StateGraph(S)
        g.add_node("enter", self.enter)
        g.add_node("think", self.think)
        g.add_node("act", self.act)
        g.add_node("report", self.report)
        g.add_edge(START, "enter")
        ways = {"enter": "enter", "think": "think", "report": "report"}
        g.add_conditional_edges("enter", lambda s: s["go"], ways)
        g.add_edge("think", "act")
        g.add_conditional_edges("act", lambda s: s["go"], ways)
        g.add_edge("report", END)
        self.graph = g.compile()

    def run(self, facts=None, ledger=None):
        t0 = time.time()
        end = self.graph.invoke({"step": self.spec["start"], "facts": dict(facts or {}),
                                 "ledger": list(ledger or []), "visits": 0},
                                {"recursion_limit": 500})
        return self.result(end, time.time() - t0)

    # ---------------------------------------------------------------- tools
    def tool(self, script, args):
        for k, v in self.vars.items():
            args = [str(a).replace("$" + k, v) for a in args]
        res = self.runner.run(script, args)
        self.stats["tool_calls"] += 1
        out = res.get("stdout") or ""
        if res.get("error"):
            out += "\nERROR: %s" % res["error"]
        if res.get("exit") not in (0, None):
            out += "\nexit code %s\n%s" % (res.get("exit"), (res.get("stderr") or "")[-1500:])
        for h in self.hide:
            out = out.replace(h, "RUN")
        self.outputs.append(out)
        self.step_out.append(out)
        self.events.append({"t": time.time(), "tool": script, "args": args, "chars": len(out)})
        if len(out) > OUT_CAP:
            out = out[:OUT_CAP * 3 // 4] + "\n[... %d characters cut ...]\n" % (len(out) - OUT_CAP) \
                + out[-OUT_CAP // 4:]
        return out or "(no output)"

    def tool_defs(self, step):
        st = self.steps[step]
        scripts = sorted(f for f in os.listdir(self.runner.tools_dir) if f.endswith((".py", ".sh")))
        return [
            {"name": "run_tool",
             "description": "Run one script of the blueprint. $TRACE and $WORK are expanded in args. "
                            "Several calls in one turn run in parallel.",
             "parameters": {"type": "object", "required": ["script", "args"], "properties": {
                 "script": {"type": "string", "enum": scripts},
                 "args": {"type": "array", "items": {"type": "string"}},
                 "why": {"type": "string", "description": "one line: what you expect to learn"}}}},
            {"name": "finish_step",
             "description": "Close the current step. Call it alone, after you have read the tool results.",
             "parameters": {"type": "object", "required": ["outcome", "summary"], "properties": {
                 "outcome": {"type": "string", "enum": list(st["outcomes"]) + ["other"],
                             "description": "how the step ended; `other` when none of the listed ways fits"},
                 "summary": {"type": "string", "description": "2-4 sentences: what you ran, what the numbers were, what you conclude"},
                 "facts": {"type": "object", "description": "values established in this step, by the names the step asks for; add any other value a later step needs"},
                 "evidence": {"type": "array", "items": {"type": "string"},
                              "description": "lines copied word for word from tool output"},
                 "next_step": {"type": "string", "enum": list(self.steps) + ["report"],
                               "description": "only to leave the blueprint's order: the step to go to, or `report` to stop now"},
                 "reason": {"type": "string", "description": "required with `other` or next_step: why you leave the guidance"}}}}]

    # ---------------------------------------------------------------- nodes
    def enter(self, s: S):
        step = s["step"]
        if step == "report" or step not in self.steps:
            return {"go": "report"}
        if s["visits"] >= MAX_VISITS:
            return {"go": "report", "conclusion": "Stopped by the harness: %d step visits." % MAX_VISITS}
        st = self.steps[step]
        self.step_out = []
        self.log("== step %s (%s)" % (step, st["kind"]))
        if st["kind"] == "fixed":
            out = "\n".join(self.tool(c[0], c[1:]) for c in st["run"])
            facts = dict(s["facts"])
            for name, rx in st.get("extract", {}).items():
                m = re.search(rx, out, re.M)
                if m:
                    facts[name] = m.group(1).strip()
            miss = [n for n in st.get("extract", {}) if n not in facts]
            entry = {"step": step, "kind": "fixed", "outcome": "done" if not miss else "values_missing",
                     "summary": "read by the harness" + (", not found: %s" % ", ".join(miss) if miss else ""),
                     "deviation": []}
            self.log("   facts: %s" % {k: facts[k] for k in st.get("extract", {}) if k in facts})
            return {"step": st["next"], "go": "enter", "facts": facts,
                    "ledger": s["ledger"] + [entry], "visits": s["visits"] + 1}
        sys_msg = SYSTEM.format(confirms=self.spec["confirms"], background=self.spec["background"],
                                lookalikes=self.spec["lookalikes"],
                                step_map=" -> ".join(self.steps) + " -> report")
        return {"go": "think", "turns": 0, "nudges": 0, "rejects": 0, "used": [], "visits": s["visits"] + 1,
                "msgs": [{"role": "system", "content": sys_msg},
                         {"role": "user", "content": self.brief(step, s)}]}

    def brief(self, step, s):
        st = self.steps[step]
        ways = []
        for name, o in st["outcomes"].items():
            nx = o.get("next")
            then = "STOP: " + o["stop"] if nx is None else "write the report" if nx == "report"                 else "go to step %s (%s)" % (nx, self.steps[nx]["goal"])
            if o.get("handoff"):
                then += " The case goes to blueprint %s." % o["handoff"]
            if o.get("line"):
                then += "  [the tool's verdict line for this: `%s ...`]" % o["line"]
            ways.append("  %s: %s -> %s" % (name, _norm(o["when"]), then))
        meanings = self.spec.get("facts", {})
        need = ["  %s: %s" % (n, meanings.get(n, "")) for n in st.get("sets", [])]
        done = ["  %s -> %s: %s" % (e["step"], e["outcome"], e["summary"]) for e in s["ledger"]]
        return "\n".join([
            "STEP %s" % step, "Goal: " + st["goal"], "",
            "Suggested commands (change them if this trace needs it):",
            *["  " + c for c in st.get("suggested", [])],
            *["  ($%s is expanded to the event list `%s`)" % kv for kv in self.vars.items()], "",
            "How to read the output:", st.get("read", "").rstrip(), "",
            "Facts this step should establish:", *(need or ["  (none)"]), "",
            "Ways this step can end:", *ways,
            "  other: none of these fits. Give next_step and your reason.", "",
            "You have about %d turns for this step." % st.get("budget", 5), "",
            "CASE FILE", "Facts: " + json.dumps(s["facts"]),
            "Steps done:", *(done or ["  (none)"])])

    def think(self, s: S):
        r = self.llm(s["msgs"], self.tool_defs(s["step"]))
        self.stats["model_calls"] += 1
        self.stats["tokens_in"] += r["in"]
        self.stats["tokens_out"] += r["out"]
        msg = {"role": "assistant", "content": r["content"]}
        if r["tool_calls"]:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["args"] if isinstance(c["args"], str) else json.dumps(c["args"])}}
                                 for c in r["tool_calls"]]
        return {"msgs": s["msgs"] + [msg], "turns": s["turns"] + 1}

    def act(self, s: S):
        step, st, msgs = s["step"], self.steps[s["step"]], list(s["msgs"])
        calls = msgs[-1].get("tool_calls") or []
        budget = st.get("budget", 5)

        def forced(outcome, why):
            self.log("   harness closed the step: " + why)
            e = {"step": step, "kind": "guided", "outcome": outcome, "summary": why, "turns": s["turns"],
                 "deviation": ["closed_by_harness"]}
            return {"go": "report", "step": "report", "ledger": s["ledger"] + [e],
                    "conclusion": "The investigation stopped in step %s: %s" % (step, why)}

        if not calls:
            if s["nudges"] >= 2:
                return forced("no_tool_call", "the model answered in text three times without a tool call")
            msgs.append({"role": "user", "content": "Use run_tool to continue this step, or finish_step to close it."})
            return {"go": "think", "msgs": msgs, "nudges": s["nudges"] + 1}

        parsed = []
        for c in calls:
            try:
                parsed.append((c, json.loads(c["function"]["arguments"] or "{}")))
            except json.JSONDecodeError:
                parsed.append((c, None))
        runs = [(c, a) for c, a in parsed if c["function"]["name"] == "run_tool" and a is not None]
        with ThreadPoolExecutor(3) as ex:       # slices are 0.2-0.9 GB of text while they are cut
            outs = dict(zip([c["id"] for c, _ in runs],
                            ex.map(lambda ca: self.tool(ca[1].get("script", ""), ca[1].get("args", [])), runs)))
        for c, a in runs:
            self.log("   run_tool %s %s" % (a.get("script"), " ".join(map(str, a.get("args", [])))))
        used = s.get("used", []) + [a.get("script") for _, a in runs]
        fin = None
        for c, a in parsed:
            name = c["function"]["name"]
            if a is None:
                content = "ERROR: the arguments were not valid JSON. Send the call again."
            elif name == "run_tool":
                content = outs[c["id"]]
            elif name == "finish_step" and runs:
                content = "ERROR: finish_step came with run_tool calls. Read the results first, then call finish_step alone."
            elif name == "finish_step":
                fin, content = a, None
            else:
                content = "ERROR: unknown tool %s" % name
            if content is not None:
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": content})
        upd = {"msgs": msgs, "used": used}

        if fin is None:
            if s["turns"] >= budget + GRACE:
                return forced("budget_used", "no finish_step after %d turns (budget %d)" % (s["turns"], budget))
            if s["turns"] >= budget:
                msgs.append({"role": "user", "content": "The budget of this step is used. Close it now with finish_step: pick the outcome that fits what you have. Closing a step does not end the investigation; the next step continues it."})
            return {**upd, "go": "think"}

        # ---- the agent closes the step: check it, then route
        fid = [c["id"] for c, a in parsed if a is fin][0]
        outcome, jump = fin.get("outcome"), fin.get("next_step")
        facts = {**s["facts"], **{k: v for k, v in (fin.get("facts") or {}).items() if v not in (None, "")}}
        o = st["outcomes"].get(outcome)
        if o and jump == o.get("next", "report"):
            jump = None                  # naming the place the outcome goes to anyway is not a jump
        problems = []
        if o is None and outcome != "other":
            problems.append("outcome must be one of: %s, other" % ", ".join(st["outcomes"]))
        if (outcome == "other" or jump) and not (fin.get("reason") or "").strip():
            problems.append("give a reason when you use `other` or next_step")
        if outcome == "other" and not jump:
            problems.append("with `other`, name next_step (a step id, or report)")
        told = told_line = None          # the outcome the decisive tool's verdict line stands for
        for line in "\n".join(self.step_out).splitlines():
            for name, oo in st["outcomes"].items():
                if oo.get("line") and oo["line"] in line:
                    told, told_line = name, line.strip()
        reasoned = bool((fin.get("reason") or "").strip())
        if told and outcome != told and not reasoned:
            problems.append("the tool's verdict line stands for outcome `%s`. To choose another outcome, "
                            "give your reason" % told)
        if o and o.get("line") and not told and not reasoned:
            problems.append("outcome `%s` rests on the verdict line of the step's decisive tool, and no such "
                            "line was printed in this step. Run the tool, or give your reason" % outcome)
        missing = [n for n in st.get("sets", []) if n not in facts] if (o and "next" in o and not jump) else []
        if missing and s["rejects"] < 1:
            problems.append("this outcome goes on to the next step, which needs these facts: %s. "
                            "Give them, or if they cannot be found use `other` with your reason" % ", ".join(missing))
        if problems and s["rejects"] < 2:
            msgs.append({"role": "tool", "tool_call_id": fid, "content": "NOT ACCEPTED: " + "; ".join(problems)})
            return {**upd, "go": "think", "rejects": s["rejects"] + 1}
        if o is None and not jump:                       # still invalid after two tries
            return forced("invalid_finish", "; ".join(problems))

        seen = _norm("\n".join(self.outputs))
        evidence = [{"text": e, "verified": _norm(e) in seen} for e in (fin.get("evidence") or [])]
        if told == outcome and _norm(told_line) not in [_norm(e["text"]) for e in evidence]:
            evidence.insert(0, {"text": told_line, "verified": True, "by": "harness"})   # copied by code
        suggested = {c.split()[0] for c in st.get("suggested", [])}
        dev = []
        if outcome == "other":
            dev.append("outcome_other")
        if jump and jump != (o or {}).get("next"):
            dev.append("jump:%s" % jump)
        extra = sorted({u for u in used if u not in suggested})
        if extra:
            dev.append("other_tools:%s" % ",".join(extra))
        if told and outcome != told:
            dev.append("against_tool_verdict:%s" % told)
        if o and o.get("line") and not told:
            dev.append("no_verdict_line")
        if missing:
            dev.append("facts_missing:%s" % ",".join(missing))
        if any(not e["verified"] for e in evidence):
            dev.append("evidence_not_in_output")
        nxt = jump or o.get("next") or "report"
        entry = {"step": step, "kind": "guided", "outcome": outcome, "summary": fin.get("summary", ""),
                 "reason": fin.get("reason", ""), "evidence": evidence, "turns": s["turns"],
                 "tools": used, "deviation": dev, "next": nxt, "tool_verdict": told_line}
        self.log("   -> %s%s  next: %s" % (outcome, ("  [left the guidance: %s | %s]" % (", ".join(dev), fin.get("reason", "")) if dev else ""), nxt))
        out = {"go": "enter" if nxt != "report" else "report", "step": nxt, "facts": facts,
               "ledger": s["ledger"] + [entry], "used": []}
        if o and "stop" in o and not jump:
            out["conclusion"] = o["stop"]
        if o and not jump and ("verdict" in o or "stop" in o):
            # the verdict is a rule of the blueprint over the outcomes the agent chose, not a
            # second free decision at the end
            out["verdict"] = o.get("verdict", "rejected")
            if o.get("handoff"):
                out["handoff"] = o["handoff"]
        return out

    def report(self, s: S):
        self.log("== report")
        submit = {"name": "submit", "description": "The final RCA statement.",
                  "parameters": {"type": "object", "required": ["agree", "statement", "confidence"], "properties": {
                      "agree": {"type": "boolean", "description": "false only if you think the verdict in the case file is wrong for this trace"},
                      "disagreement": {"type": "string", "description": "with agree=false: what in the case file speaks against the verdict"},
                      "root_cause_process": {"type": "string", "description": "program name, pid, and container (pid_ns) if known"},
                      "window": {"type": "string", "description": "start and end of the fault, UTC, as far as the trace shows"},
                      "statement": {"type": "string"},
                      "measured": {"type": "array", "items": {"type": "string"}, "description": "claims seen in the trace"},
                      "inferred": {"type": "array", "items": {"type": "string"}, "description": "claims reasoned from what was seen"},
                      "ruled_out": {"type": "array", "items": {"type": "string"}},
                      "not_checked": {"type": "array", "items": {"type": "string"}},
                      "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}}}
        case = ["Root cause this blueprint confirms or rejects: " + self.spec["confirms"],
                "Facts: " + json.dumps(s["facts"]), "Steps:"]
        for e in s["ledger"]:
            case.append("  %s -> %s: %s" % (e["step"], e["outcome"], e["summary"]))
            case += ["      evidence: " + ev["text"] for ev in e.get("evidence", []) if ev["verified"]]
        if s.get("conclusion"):
            case.append("The investigation stopped with: " + s["conclusion"])
        verdict = s.get("verdict", "inconclusive")
        case.append("VERDICT by the blueprint's rule over these outcomes: %s (confirmed = every check of the "
                    "blueprint was passed; unconfirmed = a look-alike stays open; rejected = a step showed "
                    "another cause or no fault; inconclusive = the investigation did not reach a deciding step)" % verdict.upper())
        msgs = [{"role": "system", "content": "You write the final root cause statement of a kernel-trace "
                 "investigation from its case file. Use only what the case file holds.\n" + self.spec["report"]},
                {"role": "user", "content": "\n".join(case)}]
        r = self.llm(msgs, [submit], force="submit")
        self.stats["model_calls"] += 1
        self.stats["tokens_in"] += r["in"]
        self.stats["tokens_out"] += r["out"]
        try:
            final = json.loads(r["tool_calls"][0]["args"]) if isinstance(r["tool_calls"][0]["args"], str) \
                else r["tool_calls"][0]["args"]
        except (IndexError, json.JSONDecodeError):
            final = {"agree": True, "statement": r["content"], "confidence": "low", "parse_error": True}
        return {"final": {"verdict": verdict, **final}, "verdict": verdict}

    def result(self, s, wall):
        path = [e["step"] for e in s["ledger"] if e.get("kind") != "carried"]
        devs = [(e["step"], d) for e in s["ledger"] for d in e.get("deviation", [])]
        ev = [x for e in s["ledger"] for x in e.get("evidence", [])]
        return {"blueprint": self.spec["id"], "verdict": s.get("verdict", "inconclusive"), "final": s.get("final"), "conclusion": s.get("conclusion", ""),
                "handoff": s.get("handoff", ""),
                "facts": s["facts"], "ledger": s["ledger"],
                "adherence": {"path": path, "steps_not_visited": [k for k in self.steps if k not in path],
                              "revisits": len(path) - len(set(path)), "deviations": devs,
                              "evidence_lines": len(ev), "evidence_verified": sum(x["verified"] for x in ev)},
                "stats": {**self.stats, "wall_s": round(wall, 1)}, "tool_events": self.events}


# -------------------------------------------------------------------- self-check, no trace, no API
def selftest():
    spec = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "latency",
                                            "1_svc_cpu_cap", "blueprint.yaml"), encoding="utf-8"))

    class FakeRunner:
        tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "latency", "1_svc_cpu_cap", "tools")

        def run(self, script, args):
            if script == "idx_summary.py" and "--rate" not in args:
                return {"exit": 0, "stdout": "date (UTC)    : 2026-01-02\ntrace start   : 10:00:00.1\ntrace end     : 10:04:00.2\n"}
            return {"exit": 0, "stdout": "%s said: pid 42 waits 300 of >=50ms in RUN-secret" % script}

    def fin(i, **a):
        return {"content": "", "in": 10, "out": 5, "tool_calls": [{"id": "c%d" % i, "name": "finish_step", "args": json.dumps(a)}]}

    def run(i, script):
        return {"content": "", "in": 10, "out": 5, "tool_calls": [{"id": "c%d" % i, "name": "run_tool", "args": json.dumps({"script": script, "args": ["x"]})}]}

    def scripted(plan):
        n = [0]

        def llm(msgs, tools, force=None):
            if force:
                return {"content": "", "in": 1, "out": 1, "tool_calls": [{"id": "s", "name": "submit", "args": json.dumps({"agree": True, "statement": "ok", "confidence": "high"})}]}
            n[0] += 1
            step = msgs[1]["content"].split()[1]
            return plan[step].pop(0)(n[0])
        return llm

    good = "sched_budget.py said: pid 42 waits 300 of >=50ms in RUN"
    # 1. the blueprint's own order, with one rejected finish (facts missing) and one invented evidence line
    plan = {
        "find_window": [lambda i: run(i, "idx_summary.py"), lambda i: fin(i, outcome="window_found", summary="s", facts={"window_start": "10:01:00", "window_end": "10:03:00"})],
        "find_victim": [lambda i: run(i, "sched_budget.py"),
                        lambda i: fin(i, outcome="one_victim", summary="s"),                                    # rejected: facts missing
                        lambda i: fin(i, outcome="one_victim", summary="s", evidence=[good, "made up line"],
                                      facts={"victim_pid": 42, "base_start": "10:00:30", "fault_start": "10:01:30"})],
        "compare_budget": [lambda i: fin(i, outcome="starved", summary="s")],
        "ceiling": [lambda i: fin(i, outcome="ceiling_below_period", summary="s", facts={"period_ms": 100, "ceiling_ms": 25, "cap_cores": 0.25})],
        "rule_out": [lambda i: fin(i, outcome="cpus_idle", summary="s", facts={"idle_share": "97%"})],
        "identify": [lambda i: fin(i, outcome="identified", summary="s", facts={"victim_name": "java"})],
    }
    r = Investigation(spec, FakeRunner(), scripted(plan), hide=["RUN-secret"], log=lambda *_: None).run()
    a = r["adherence"]
    assert a["path"] == ["check_trace", "find_window", "find_victim", "compare_budget", "ceiling", "rule_out", "identify"], a["path"]
    assert r["facts"]["day"] == "2026-01-02" and r["facts"]["victim_pid"] == 42
    assert a["deviations"] == [("find_victim", "evidence_not_in_output")], a["deviations"]
    assert (a["evidence_lines"], a["evidence_verified"]) == (2, 1)
    assert r["verdict"] == "confirmed" and r["final"]["verdict"] == "confirmed" and not a["steps_not_visited"]

    # 2. the agent leaves the guidance: another tool, a jump past two steps, then a stop outcome
    plan = {
        "find_window": [lambda i: fin(i, outcome="no_clear_change", summary="s", facts={"window_start": "10:00:00", "window_end": "10:04:00"})],
        "find_victim": [lambda i: run(i, "wake_graph.py"),
                        lambda i: fin(i, outcome="other", summary="s"),                                         # rejected: no reason, no next_step
                        lambda i: fin(i, outcome="other", summary="s", next_step="rule_out", reason="one pid is clear already", facts={"victim_pid": 7})],
        "rule_out": [lambda i: fin(i, outcome="neighbor", summary="s", next_step="report", reason="r")],   # not a jump
    }
    r = Investigation(spec, FakeRunner(), scripted(plan), log=lambda *_: None).run()
    a = r["adherence"]
    assert a["path"] == ["check_trace", "find_window", "find_victim", "rule_out"], a["path"]
    assert ("find_victim", "outcome_other") in a["deviations"] and ("find_victim", "jump:rule_out") in a["deviations"]
    assert ("find_victim", "other_tools:wake_graph.py") in a["deviations"]
    assert a["steps_not_visited"] == ["compare_budget", "ceiling", "identify"]
    assert r["conclusion"].startswith("A noisy neighbor") and r["verdict"] == "rejected"

    # 3. a model that never closes the step is stopped by the harness
    plan = {"find_window": [lambda i: run(i, "idx_summary.py")] * 10}
    r = Investigation(spec, FakeRunner(), scripted(plan), log=lambda *_: None).run()
    assert r["verdict"] == "inconclusive" and r["ledger"][-1]["outcome"] == "budget_used" and r["stats"]["tool_calls"] == 1 + 5
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("blueprint", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--work", help="scratch folder for slices (default: a temp folder)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    here = os.path.dirname(os.path.abspath(__file__))
    load_env(os.path.join(here, "..", "..", ".env"))
    sys.path.insert(0, here)
    import blueprints
    import tempfile
    work = a.work or os.path.join(tempfile.gettempdir(), "bp_graph_work", "run_%d" % int(time.time()))
    remote = ":" in a.run_dir and len(a.run_dir.split(":", 1)[0]) > 1     # "<host>:/path", see blueprints.Runner
    run_abs = a.run_dir.split(":", 1)[1] if remote else os.path.abspath(a.run_dir)
    # the model must not see the run's name: it names the fault
    hide = [blueprints._wsl_path(run_abs), run_abs, run_abs.replace("\\", "/"), os.path.basename(run_abs.rstrip("/"))]
    llm, bp, facts, ledger, results = openai_llm(), os.path.abspath(a.blueprint), {}, [], []
    while True:                       # one blueprint, then the one it hands the case to, if any
        spec = yaml.safe_load(open(bp, encoding="utf-8"))
        print("#### blueprint %s" % spec["id"])
        runner = blueprints.Runner(os.path.join(os.path.dirname(bp), "tools"), a.run_dir, work)
        res = Investigation(spec, runner, llm, hide=hide).run(facts, ledger)
        results.append(res)
        nxt = os.path.join(os.path.dirname(os.path.dirname(bp)), res["handoff"] or "-", "blueprint.yaml")
        if not res["handoff"] or not os.path.exists(nxt) or len(results) >= 3:
            break
        facts = res["facts"]
        ledger = [{"step": "(handed over by blueprint %s)" % spec["id"], "kind": "carried", "outcome": res["verdict"],
                   "summary": res["conclusion"] + " " + (res["final"] or {}).get("statement", ""), "deviation": []}]
        bp = nxt
    out = a.out or os.path.join(work, "result.json")
    json.dump(results, open(out, "w", encoding="utf-8"), indent=1)
    for res in results:
        print(json.dumps({k: res[k] for k in ("blueprint", "verdict", "handoff", "final", "conclusion", "adherence", "stats")}, indent=1))
    print("saved:", out)


if __name__ == "__main__":
    main()
