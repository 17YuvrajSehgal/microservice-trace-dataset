#!/usr/bin/env python3
"""Replay one agent investigation, readably, for a live audience.

Built for the Ciena meeting. It replays a RECORDED transcript by default, so it needs no
network, no cluster and no API key and cannot fail in the room. `--live` runs the real agent
instead, for when the connection is known good.

The recorded run is deliberately the hardest condition we have: `nohint`. Nobody told the agent
an incident happened, when it was, or where to look. It got a raw kernel trace and seven
read-only tools.

    python demo_agent.py                      # replay, pause between sections
    python demo_agent.py --pace 0             # replay, no pauses (rehearsal)
    python demo_agent.py --step               # wait for Enter between sections
    python demo_agent.py --live RUN_DIR       # run the real agent
"""
from __future__ import annotations
import argparse, json, os, sys, textwrap, time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "demo", "demo-transcript.jsonl")
W = 96


# The model writes curly quotes and dashes; a Windows console in cp1252 turns those into
# replacement characters mid-sentence, which looks like a bug to an audience. Force UTF-8 and
# fall back to ASCII lookalikes if the terminal still refuses.
_SUBS = {"’": "'", "‘": "'", "“": '"', "”": '"',
         "—": "-", "–": "-", "…": "...", " ": " "}
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                       # noqa: BLE001
    pass


def clean(s):
    s = str(s or "")
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    return s


def rule(ch="="):
    print(ch * W)


def head(title, sub=""):
    print()
    rule()
    print(title)
    if sub:
        print(sub)
    rule()


def wrap(s, indent="   ", width=W - 6):
    for para in clean(s).split("\n"):
        for ln in textwrap.wrap(para, width) or [""]:
            print(indent + ln)


def pause(a):
    if a.step:
        try:
            input("\n      [Enter]")
        except EOFError:
            pass
    elif a.pace:
        time.sleep(a.pace)


def replay(path, a):
    d = json.load(open(path, encoding="utf-8", errors="replace"))
    ev = d.get("events", [])
    meta = d.get("meta", {})

    head("AGENT ROOT-CAUSE ANALYSIS - one incident, kernel trace only",
         "no metrics, no logs, no distributed traces")
    print("   incident       %s" % meta.get("incident_alias", "?"))
    print("   condition      %s" % ("NO HINT - not told an incident happened, or when, or where"
                                    if meta.get("problem_hint") is None else "symptom given"))
    print("   model          %s" % meta.get("model", "?"))
    print("   tools          7 read-only, over the raw trace. One of them runs code the agent")
    print("                  writes itself.")
    pause(a)

    # --- the plan
    for e in ev:
        if e.get("type") == "plan":
            head("1. IT PLANS", "a planner splits the work; the workers run in parallel")
            for i, s in enumerate(e.get("subtasks") or [], 1):
                print("   %d. %s" % (i, s.get("title", "?")))
                wrap(s.get("instruction", ""), "        ")
                print()
            pause(a)
            break

    # --- the code it wrote
    snips = [s for e in ev if e.get("type") == "code_snippets"
             for s in (e.get("snippets") or [])
             if (s.get("result") or {}).get("stdout")]
    if snips:
        head("2. IT WRITES AND RUNS ITS OWN ANALYSIS CODE",
             "the fixed tools answer fixed questions; this answers the rest")
        for s in snips[:3]:
            if s.get("why"):
                print("   Q: %s" % s["why"])
            code = (s.get("code") or "").strip().split("\n")
            for ln in code[:9]:
                print("      | %s" % clean(ln)[:W - 10])
            if len(code) > 9:
                print("      | ... (%d more lines)" % (len(code) - 9))
            out = ((s.get("result") or {}).get("stdout") or "").strip().split("\n")
            print("      ->")
            for ln in out[:8]:
                print("         %s" % clean(ln)[:W - 12])
            if len(out) > 8:
                print("         ... (%d more lines)" % (len(out) - 8))
            print()
            pause(a)

    # --- what it recorded
    finds = [e.get("finding") for e in ev if e.get("type") == "finding"]
    if finds:
        head("3. IT RECORDS WHAT IT FINDS", "%d findings, each with the numbers behind it"
             % len(finds))
        for f in finds[:5]:
            print("   - %s" % clean(f.get("claim", ""))[:W - 6])
            print("     where: %-28s when: %s"
                  % (str(f.get("where", "?"))[:28], str(f.get("when", "?"))[:34]))
            print()
        if len(finds) > 5:
            print("   ... and %d more" % (len(finds) - 5))
        pause(a)

    # --- the verdict
    fin = (d.get("final") or {})
    dx = fin.get("diagnosis") or {}
    head("4. IT COMMITS TO AN ANSWER")
    print("   WHAT")
    wrap(dx.get("what_is_wrong", ""))
    print()
    print("   WHERE      %s   (%s)" % (dx.get("root_cause_service", "?"),
                                       dx.get("culprit_kind", "?")))
    print("   WHEN       %s" % dx.get("incident_window", "?"))
    print("   FAULT      %s        confidence %s"
          % (dx.get("fault_type", "?"), dx.get("confidence", "?")))
    print()
    print("   HOW IT KNOWS")
    wrap(clean(dx.get("evidence", ""))[:700])
    pause(a)

    # --- the answer
    gt = d.get("_ground_truth") or {}
    if gt:
        head("5. GROUND TRUTH", "the agent never had access to any of this")
        print("   injected       %s" % gt.get("name", "?"))
        print("   target         %s" % gt.get("target_service", "?"))
        print("   parameters     %s" % json.dumps(gt.get("parameters", {})))
        print("   window         %s  ->  %s" % (gt.get("injection_start_utc", "?"),
                                                gt.get("injection_end_utc", "?")))
        sc = d.get("_score") or {}
        print()
        print("   SCORED         where=%s   container_correct=%s   window=%s (IoU %s)"
              % (sc.get("where"), sc.get("container_correct"),
                 sc.get("window_verdict"), sc.get("window_iou")))
    rule()
    print()
    print("   The kernel records no service name. `pid_ns` is one number per container, so")
    print("   naming the container IS the most precise answer this data allows.")
    print()
    print("   Honest framing: this is one run. Across 30 runs of this problem with the")
    print("   blueprint it names the right container 10 times; without it, once.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", default=DEFAULT)
    ap.add_argument("--pace", type=float, default=2.5, help="seconds between sections")
    ap.add_argument("--step", action="store_true", help="wait for Enter instead")
    ap.add_argument("--live", default="", help="run the real agent on this run dir")
    a = ap.parse_args()

    if a.live:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "agentic-rca"))
        sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
        from stratatrace import load_run
        import agent_v2
        out = os.path.join("/tmp", "demo-live.json")
        agent_v2.diagnose(load_run(a.live), app=os.environ.get("STRATATRACE_APP"),
                          transcript_path=out, condition="demo")
        return replay(out, a) or 0

    if not os.path.exists(a.transcript):
        print("no transcript at %s" % a.transcript)
        print("run with --transcript PATH, or fetch the recorded one into demo/")
        return 1
    replay(a.transcript, a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
