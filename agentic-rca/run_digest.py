#!/usr/bin/env python3
"""Digest a whole matrix into one readable file, so 60 transcripts can be reviewed without
opening 60 files of 1.2 MB each.

`inspect_run.py` opens ONE run all the way up, which is what you want when something looks
wrong. This is the other half: the shape of every run side by side, so you can see which ones
are worth opening.

Everything here comes off disk - no model calls, no cluster jobs - so it can be re-run as often
as you like while tuning.

    python run_digest.py <results-dir> [--out digest.md]
"""
from __future__ import annotations
import argparse
import collections
import glob
import json
import os
import statistics
import sys


def human(n):
    return "%.0fk" % (n / 1000.0) if n and n >= 1000 else str(n or 0)


def pick(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * (len(v) - 1)))] if v else 0


def one(tp):
    """Everything worth knowing about a single run, off its transcript and score."""
    try:
        d = json.load(open(tp, encoding="utf-8", errors="replace"))
    except Exception:
        return None
    ev, meta = d.get("events", []), (d.get("meta") or {})
    fin = d.get("final") or {}
    sp = os.path.join(os.path.dirname(tp), "score.json")
    sc = {}
    if os.path.exists(sp):
        try:
            sc = json.load(open(sp, encoding="utf-8"))
        except Exception:
            pass
    tools = collections.Counter(e.get("tool") for e in ev if e.get("type") == "tool_execution")
    cut = sum(1 for e in ev if e.get("type") == "tool_execution" and e.get("truncated"))
    elided = sum(len(e.get("elided") or []) for e in ev if e.get("type") == "thread_step")
    peak = max([int((((e.get("response") or {}).get("usage") or {}).get("prompt_tokens")) or 0)
                for e in ev if e.get("type") == "api_response"] or [0])
    comp = next((e.get("computed") for e in ev if e.get("type") == "computed"), []) or []
    snips = next((e.get("snippets") for e in ev if e.get("type") == "code_snippets"), []) or []
    errs = sum(1 for s in snips if (s.get("result") or {}).get("error"))
    dx = fin.get("diagnosis") or {}
    return {
        "run": meta.get("run_id"), "ask": meta.get("ask"), "arm": meta.get("arm"),
        "rep": meta.get("repeat"), "model": meta.get("model"),
        "where": sc.get("where"), "ok": sc.get("container_correct"),
        "fault_ok": sc.get("fault_ok"), "verdict": sc.get("window_verdict"),
        "iou": sc.get("window_iou"), "onset": sc.get("onset_error_s"),
        "gated": sc.get("earliness_gated"),
        "answer": str(dx.get("root_cause_service") or "")[:34],
        "calls": sum(tools.values()), "cut": cut, "elided": elided,
        "findings": sum(1 for e in ev if e.get("type") == "finding"),
        "computed": len(comp), "snippets": len(snips), "snippet_errors": errs,
        "nudged": sum(1 for e in ev if e.get("type") == "worker_nudge"),
        "peak_tok": peak,
        "tok_in": (fin.get("tokens") or {}).get("in", 0),
        "wall": fin.get("wall_s"), "tools": tools, "path": tp,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows = [r for r in (one(t) for t in
                        sorted(glob.glob(os.path.join(a.results, "*", "*", "*", "*", "*",
                                                      "transcript.jsonl")))) if r]
    if not rows:
        print("no transcripts under %s" % a.results)
        return 1

    L = []
    w = L.append
    w("# Run digest - %s" % os.path.basename(a.results.rstrip("/")))
    w("")
    w("%d runs, model `%s`. Generated from the transcripts on disk; no model calls."
      % (len(rows), rows[0]["model"]))
    w("")

    # ---- the health checks that decide whether the numbers mean anything
    w("## Is the harness sound?")
    w("")
    w("| check | result |")
    w("|---|---|")
    bad_cut = sum(r["cut"] for r in rows)
    bad_el = sum(r["elided"] for r in rows)
    w("| tool results truncated | **%d** %s |" % (bad_cut, "" if not bad_cut else "<- context was lost"))
    w("| thread messages elided | **%d** %s |" % (bad_el, "" if not bad_el else "<- check what"))
    w("| runs with no findings recorded | %d |" % sum(1 for r in rows if not r["findings"]))
    w("| workers nudged for silence | %d |" % sum(r["nudged"] for r in rows))
    w("| code snippets that errored | %d of %d |"
      % (sum(r["snippet_errors"] for r in rows), sum(r["snippets"] for r in rows)))
    w("| peak prompt, p90 / max | %s / %s tokens (%.1f%% of 400k) |"
      % (human(pick([r["peak_tok"] for r in rows], 0.9)),
         human(max(r["peak_tok"] for r in rows)),
         100.0 * max(r["peak_tok"] for r in rows) / 400000))
    w("")

    # ---- the result
    w("## Result")
    w("")
    n = len(rows)
    right = sum(1 for r in rows if r["ok"] is True)
    wrong = sum(1 for r in rows if r["ok"] is False)
    unv = sum(1 for r in rows if str(r["where"] or "").startswith("container") and r["ok"] is None)
    w("| | |")
    w("|---|---|")
    w("| named the right container | **%d / %d** |" % (right, n))
    w("| named the wrong one | %d |" % wrong)
    w("| named one we cannot verify | %d |" % unv)
    w("| fault type right | %d / %d |" % (sum(1 for r in rows if r["fault_ok"]), n))
    w("| window hit | %d / %d |" % (sum(1 for r in rows if r["verdict"] == "hit"), n))
    ons = [r["onset"] for r in rows if r["onset"] is not None]
    if ons:
        w("| noticed, median / p90 | %+.0fs / %+.0fs |" % (statistics.median(ons), pick(ons, 0.9)))
    ga = [r["gated"] for r in rows if r["gated"] is not None]
    if ga:
        w("| earliness (gated), mean | %.3f |" % (sum(ga) / len(ga)))
    w("| abstained on the window | %d |" % sum(1 for r in rows if r["verdict"] == "abstained"))
    w("")

    # ---- by arm, which is the comparison the study exists to make
    w("## By arm")
    w("")
    w("| arm | ask | n | container right | window hit | noticed | tokens/run |")
    w("|---|---|---|---|---|---|---|")
    for arm in ("given", "none"):
        for ask in ("hint", "nohint"):
            g = [r for r in rows if r["arm"] == arm and r["ask"] == ask]
            if not g:
                continue
            o = [r["onset"] for r in g if r["onset"] is not None]
            w("| %s | %s | %d | %d | %d | %s | %s |"
              % (arm, ask, len(g), sum(1 for r in g if r["ok"] is True),
                 sum(1 for r in g if r["verdict"] == "hit"),
                 "%+.0fs" % statistics.median(o) if o else "-",
                 human(statistics.median([r["tok_in"] for r in g]))))
    w("")

    # ---- cost
    w("## Cost")
    w("")
    ti = [r["tok_in"] for r in rows]
    wa = [r["wall"] or 0 for r in rows]
    w("| | median | p90 | total |")
    w("|---|---|---|---|")
    w("| prompt tokens | %s | %s | %s |"
      % (human(statistics.median(ti)), human(pick(ti, 0.9)), human(sum(ti))))
    w("| wall seconds | %.0f | %.0f | %.0f |"
      % (statistics.median(wa), pick(wa, 0.9), sum(wa)))
    w("")

    # ---- every run, so a reader can pick which to open
    w("## Every run")
    w("")
    w("| run | ask/arm | answer | where | window | noticed | calls | code | find | tok |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["ask"] or "", x["arm"] or "", x["rep"] or 0)):
        w("| %s | %s/%s | `%s` | %s | %s %s | %s | %d | %d/%d | %d | %s |"
          % (str(r["run"])[:26], r["ask"], r["arm"], r["answer"] or "-", r["where"],
             r["verdict"], r["iou"] if r["iou"] is not None else "",
             "%+.0fs" % r["onset"] if r["onset"] is not None else "-",
             r["calls"], r["snippets"] - r["snippet_errors"], r["snippets"],
             r["findings"], human(r["tok_in"])))
    w("")
    w("`code` is snippets that ran / snippets attempted. To open one run in full:")
    w("")
    w("```")
    w("python agentic-rca/inspect_run.py <the run's transcript.jsonl> --full")
    w("```")

    text = "\n".join(L) + "\n"
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
        print("wrote %s (%d runs)" % (a.out, len(rows)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
