#!/usr/bin/env python3
"""Write BLUEPRINT.md from blueprint.yaml, so the text people read and the steps the agent
runs come from one source.

    python bp_render.py ../latency/24_code_unbounded_cache/blueprint.yaml [more.yaml ...]
"""
import os
import sys

import yaml


def render(spec):
    L = ["<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->",
         "# Blueprint: " + spec.get("title", spec["id"]), "", "| | |", "|---|---|"]
    for label, key in (("Problem class", "problem_class"), ("Root cause this blueprint confirms or rejects", "confirms"),
                       ("Evidence", "evidence"), ("Not used", "not_used")):
        if spec.get(key):
            L.append("| %s | %s |" % (label, " ".join(spec[key].split())))
    for label, key in (("When to use this.", "when_to_use"), ("Status.", "status")):
        if spec.get(key):
            L += ["", "**%s** %s" % (label, " ".join(spec[key].split()))]
    L += ["", "## Part 1. Background", "", spec["background"].rstrip(), "",
          "Problems that look similar:", ""] + ["- " + x for x in spec["lookalikes"].strip().splitlines()]
    L += ["", "## Part 2. What you need", ""]
    if spec.get("tools"):
        L += ["| Script | What it does | Usage |", "|---|---|---|"]
        L += ["| `%s` | %s | `%s` |" % (n, t["does"], t["usage"]) for n, t in spec["tools"].items()]
    for k, v in (spec.get("vars") or {}).items():
        L += ["", "`%s='%s'`" % (k, v)]
    L += ["", "## Part 3. Procedure", "",
          "The commands are suggestions that worked on the labelled runs. Change them when the trace needs it."]
    for n, (sid, st) in enumerate(spec["steps"].items(), 1):
        L += ["", "### Step %d. %s (`%s`)" % (n, st["goal"], sid), ""]
        cmds = [" ".join(c) for c in st.get("run", [])] + st.get("suggested", [])
        L += ["```", *cmds, "```"]
        if st.get("read"):
            L += ["", st["read"].rstrip()]
        if st["kind"] == "fixed":
            L += ["", "Read from the output: %s. Next: `%s`." % (", ".join("`%s`" % k for k in st.get("extract", {})), st["next"])]
            continue
        if st.get("sets"):
            L += ["", "Write down: " + ", ".join("`%s` (%s)" % (k, spec["facts"].get(k, "")) for k in st["sets"]) + "."]
        L += ["", "| The step ends with | When | Verdict line | Then |", "|---|---|---|---|"]
        for name, o in st["outcomes"].items():
            then = "go to `%s`" % o["next"] if "next" in o else "**Stop.** " + o["stop"]
            if o.get("handoff"):
                then += " Hand the case to blueprint `%s`." % o["handoff"]
            if o.get("verdict") or "stop" in o:
                then += " Root cause **%s**%s." % (o.get("verdict", "rejected"), " (`%s`)" % o["fault_type"] if o.get("fault_type") else "")
            L.append("| `%s` | %s | %s | %s |" % (name, " ".join(o["when"].split()),
                                                 "`%s ...`" % o["line"] if o.get("line") else "", then))
    L += ["", "### Report", "", spec["report"].rstrip()]
    if spec.get("measured"):
        L += ["", "## Part 4. Measured, and limits", ""] + ["- " + m for m in spec["measured"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    for p in sys.argv[1:]:
        out = os.path.join(os.path.dirname(os.path.abspath(p)), "BLUEPRINT.md")
        open(out, "w", encoding="utf-8", newline="\n").write(render(yaml.safe_load(open(p, encoding="utf-8"))))
        print("wrote", out)
