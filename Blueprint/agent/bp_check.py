#!/usr/bin/env python3
"""Check blueprint.yaml files against the format (Blueprint/latency/METHOD.md).

    python bp_check.py ../latency/*/blueprint.yaml

ERROR  = the harness or the renderer would break, or a claim has no source.
WARN   = look at it: a number in the yaml that is not in README_v1.md / RESULTS.md / a tool.
Exit code 1 if any file has an error.
"""
import glob
import os
import re
import sys

import yaml

TOP = ["id", "fault_type", "title", "problem_class", "confirms", "evidence", "when_to_use", "status",
       "background", "lookalikes", "tools", "facts", "start", "steps", "report", "measured"]
VERDICTS = {"confirmed", "unconfirmed", "rejected", "inconclusive"}


def check(path):
    err, warn = [], []
    folder = os.path.dirname(os.path.abspath(path))
    spec = yaml.safe_load(open(path, encoding="utf-8"))
    tdir = os.path.join(folder, "tools")
    scripts = set(os.listdir(tdir)) if os.path.isdir(tdir) else set()
    source = "\n".join(open(os.path.join(tdir, f), encoding="utf-8", errors="replace").read()
                       for f in scripts if f.endswith((".py", ".sh")))
    err += ["missing key: " + k for k in TOP if not spec.get(k)]
    if err:
        return err, warn
    steps, facts, vars_ = spec["steps"], spec["facts"], spec.get("vars") or {}
    if spec["start"] not in steps:
        err.append("start is not a step")
    err += ["tools: no such script " + t for t in spec["tools"] if t not in scripts]
    confirmed = False
    reach, todo = set(), [spec["start"]]
    while todo:
        k = todo.pop()
        if k in reach or k not in steps:
            continue
        reach.add(k)
        st = steps[k]
        todo += [st["next"]] if st.get("kind") == "fixed" else [o.get("next") for o in st.get("outcomes", {}).values()]
    err += ["step not reachable: " + k for k in steps if k not in reach]
    for sid, st in steps.items():
        w = "step %s: " % sid
        cmds = [" ".join(map(str, c)) for c in st.get("run", [])] + st.get("suggested", [])
        for c in cmds:
            if c.split()[0] not in scripts:
                err.append(w + "no such script: " + c.split()[0])
            for v in re.findall(r"\$([A-Z_0-9]+)", c):
                if v not in ("TRACE", "WORK") and v not in vars_:
                    err.append(w + "$%s is not in vars" % v)
        if st.get("kind") == "fixed":
            err += [w + "fixed step needs " + k for k in ("goal", "run", "extract", "next") if not st.get(k)]
            if st.get("next") not in steps:
                err.append(w + "next is not a step")
            continue
        if st.get("kind") != "guided":
            err.append(w + "kind must be fixed or guided")
            continue
        err += [w + "guided step needs " + k for k in ("goal", "suggested", "read", "outcomes", "budget") if not st.get(k)]
        err += [w + "sets `%s` is not in facts" % f for f in st.get("sets", []) if f not in facts]
        for name, o in (st.get("outcomes") or {}).items():
            ww = w + "outcome %s: " % name
            if not o.get("when"):
                err.append(ww + "no `when`")
            if ("next" in o) == ("stop" in o):
                err.append(ww + "needs exactly one of next / stop")
            if "next" in o and o["next"] != "report" and o["next"] not in steps:
                err.append(ww + "next is not a step")
            if o.get("verdict") and o["verdict"] not in VERDICTS:
                err.append(ww + "verdict must be one of %s" % sorted(VERDICTS))
            confirmed |= o.get("verdict") == "confirmed"
            err += [ww + "sets `%s` is not in facts" % f for f in o.get("sets", []) if f not in facts]
            if o.get("fault_type") and o.get("verdict") != "confirmed":
                err.append(ww + "fault_type belongs on a confirmed outcome")
            if o.get("line") and o["line"] not in source:
                err.append(ww + "line `%s` is not printed by any tool in tools/" % o["line"])
            if o.get("handoff") and not os.path.isdir(os.path.join(os.path.dirname(folder), o["handoff"])):
                err.append(ww + "handoff folder does not exist: " + o["handoff"])
    if not confirmed:
        err.append("no outcome has verdict: confirmed")
    # every number in the yaml's prose should come from the README, the results file or a tool
    known = source
    for f in ("README_v1.md", "RESULTS.md"):
        if os.path.exists(os.path.join(folder, f)):
            known += open(os.path.join(folder, f), encoding="utf-8").read()
    known = known.replace(",", "")
    prose = " ".join([spec["status"], spec["background"], spec["lookalikes"], spec["when_to_use"], spec["report"],
                      " ".join(spec["measured"])] + [st.get("read", "") + st.get("goal", "") + " ".join(
                          o.get("when", "") + o.get("stop", "") for o in st.get("outcomes", {}).values())
                          for st in steps.values()])
    nums = sorted({n for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])", prose.replace(",", "")) if len(n) > 1})
    missing = [n for n in nums if n not in known]
    if missing:
        warn.append("numbers not found in README_v1.md / RESULTS.md / tools: " + ", ".join(missing))
    return err, warn


if __name__ == "__main__":
    bad = 0
    for p in [q for a in sys.argv[1:] for q in sorted(glob.glob(a))]:
        err, warn = check(p)
        bad += bool(err)
        print("%s  %s" % ("ERROR" if err else "ok   ", os.path.basename(os.path.dirname(os.path.abspath(p)))))
        for e in err:
            print("    ERROR " + e)
        for w in warn:
            print("    WARN  " + w)
    sys.exit(1 if bad else 0)
