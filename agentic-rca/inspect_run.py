#!/usr/bin/env python3
"""Open one run all the way up: every tool call, every snippet, the scratchpad, and what the
synthesiser was actually handed.

Written because three separate results this week were lost between a worker computing something
and the synthesiser seeing it, and none of the existing summaries would have shown that. The
questions this answers are the ones a summary cannot:

  - did any tool result get cut, and if so what was dropped
  - did a worker's message thread get trimmed, and did that lose a tool result
  - what did each worker write down, and what did it compute but NOT write down
  - what text did the synthesiser actually receive
  - is anything near a context limit

    python inspect_run.py <transcript.jsonl> [--full]
"""
from __future__ import annotations
import argparse
import collections
import json
import sys


def human(n):
    return "%.1fk" % (n / 1000.0) if n >= 1000 else str(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--full", action="store_true",
                    help="print every tool result and snippet in full, not just the summary")
    ap.add_argument("--chars", type=int, default=600, help="chars of each body to show")
    a = ap.parse_args()

    d = json.load(open(a.transcript, encoding="utf-8", errors="replace"))
    ev = d.get("events", [])
    meta = d.get("meta") or {}
    final = d.get("final") or {}

    print("=" * 100)
    print("RUN %s   agent=%s   model=%s" % (meta.get("run_id"), meta.get("agent"),
                                            meta.get("model")))
    print("=" * 100)
    print("caps in force: default %s, per tool %s"
          % (meta.get("sent_cap_chars"), meta.get("sent_cap_by_tool")))
    print()

    # ---------------------------------------------------------------- tool calls
    print("-" * 100)
    print("1. TOOL CALLS - was anything cut?")
    print("-" * 100)
    cut = 0
    per_tool = collections.Counter()
    for e in ev:
        if e.get("type") != "tool_execution":
            continue
        t = e.get("tool")
        per_tool[t] += 1
        full = len(json.dumps(e.get("result"), default=str)) if e.get("result") is not None else 0
        sent = len(e.get("sent") or "")
        flag = ""
        if e.get("truncated"):
            cut += 1
            flag = "  <<< CUT: %s" % json.dumps(e.get("dropped"))[:90]
        print("  [%-11s] %-14s full %-8s sent %-8s cap %-7s%s"
              % (e.get("node", "-"), t, human(full), human(sent), e.get("sent_cap", "-"), flag))
        if a.full and e.get("sent"):
            print("      %s" % (e["sent"][:a.chars]).replace(chr(10), " | "))
    print()
    print("  %d calls, %d truncated%s" % (sum(per_tool.values()), cut,
                                          "  <-- CONTEXT WAS CUT" if cut else "  <-- nothing cut"))

    # ---------------------------------------------------------------- thread trimming
    print()
    print("-" * 100)
    print("2. WORKER THREADS - did trimming discard a tool result?")
    print("-" * 100)
    stubs = [e for e in ev if e.get("type") == "api_response"
             and "elided to keep this thread small" in json.dumps(e.get("response", ""))[:200000]]
    peak = collections.defaultdict(int)
    for e in ev:
        if e.get("type") != "api_response":
            continue
        u = ((e.get("response") or {}).get("usage") or {})
        peak[e.get("node", "-")] = max(peak[e.get("node", "-")],
                                       int(u.get("prompt_tokens") or 0))
    for n, p in sorted(peak.items()):
        print("  %-12s peak prompt %s tokens" % (n, human(p)))
    print()
    print("  worker threads that had results elided: %d" % len(stubs))
    biggest = max(peak.values()) if peak else 0
    print("  biggest single prompt: %s tokens  (%s of a 400k window)"
          % (human(biggest), "%.1f%%" % (100.0 * biggest / 400000)))

    # ---------------------------------------------------------------- scratchpad
    print()
    print("-" * 100)
    print("3. SCRATCHPAD - what each worker chose to record")
    print("-" * 100)
    byw = collections.defaultdict(list)
    for e in ev:
        if e.get("type") == "finding":
            byw[e.get("node", "-")].append(e.get("finding") or {})
    for n in sorted(byw):
        print("  %s  (%d findings)" % (n, len(byw[n])))
        for f in byw[n]:
            print("     %s%s" % ("RULED OUT: " if f.get("ruled_out") else "",
                                 str(f.get("claim"))[:a.chars if a.full else 150]))
            print("        where=%s  when=%s  conf=%s"
                  % (str(f.get("where"))[:40], str(f.get("when"))[:30], f.get("confidence")))
    nod = [e.get("node") for e in ev if e.get("type") == "worker_nudge"]
    print()
    print("  total findings: %d   workers nudged for recording nothing: %s"
          % (sum(len(v) for v in byw.values()), nod or "none"))

    # ---------------------------------------------------------------- computed
    print()
    print("-" * 100)
    print("4. COMPUTED - what the code actually produced, recorded or not")
    print("-" * 100)
    comp = next((e.get("computed") for e in ev if e.get("type") == "computed"), None)
    if comp is None:
        print("  (this run predates the computed-capture fix)")
    else:
        for c in comp:
            print("  [%-11s] %s%s" % (c.get("node"), (c.get("why") or "")[:70],
                                      "   TRUNCATED" if c.get("truncated") else ""))
            body = (c.get("output") or "")
            print("      %s" % (body[:a.chars if a.full else 200]).replace(chr(10), " | "))
            if c.get("error"):
                print("      ERROR: %s" % c["error"][:150])
        print()
        print("  %d computations captured, %d truncated"
              % (len(comp), sum(1 for c in comp if c.get("truncated"))))

    # ---------------------------------------------------------------- synthesiser input
    print()
    print("-" * 100)
    print("5. WHAT THE SYNTHESISER RECEIVED")
    print("-" * 100)
    sp = next((e for e in ev if e.get("type") == "synth_prompt"), None)
    if not sp:
        print("  (no synth_prompt event)")
    else:
        txt = sp.get("user") or ""
        print("  length: %s chars (~%s tokens)" % (human(len(txt)), human(len(txt) // 4)))
        print("  contains a RECORDED section: %s" % ("WHAT THE WORKERS RECORDED" in txt))
        print("  contains a COMPUTED section: %s" % ("WHAT THE WORKERS COMPUTED" in txt))
        print("  says results were omitted for length: %s" % ("further results omitted" in txt))
        if a.full:
            print()
            print(txt)

    # ---------------------------------------------------------------- verdict
    print()
    print("-" * 100)
    print("6. OUTCOME")
    print("-" * 100)
    dx = final.get("diagnosis") or {}
    for k in ("root_cause_service", "culprit_kind", "fault_type", "incident_window",
              "confidence"):
        print("  %-20s %s" % (k, str(dx.get(k))[:110]))
    print("  %-20s %s" % ("stop reason", final.get("stop")))
    tk = final.get("tokens") or {}
    print("  %-20s in %s / out %s   wall %ss"
          % ("cost", human(tk.get("in", 0)), human(tk.get("out", 0)), final.get("wall_s")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
