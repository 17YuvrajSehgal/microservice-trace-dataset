#!/usr/bin/env python3
"""Run ONE question-2 cell end to end and dump everything it produced.

The point is not the answer - it is to prove the plumbing before spending 60 runs on it:
does the blueprint actually reach the model, does a ranked answer come back, and does every
metric we promised get written to disk?

    ~/q2venv/bin/python q2_run_one.py --arm given --ask hint
    ~/q2venv/bin/python q2_run_one.py --arm none  --ask nohint

Writes <out>/<problem>/<run_id>/<ask>/<arm>/rep<N>/ exactly as the full matrix will.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
sys.path.insert(0, ROOT)


def _clock_s(s: str):
    """'HH:MM:SS[.frac]' -> seconds. None if it does not parse."""
    try:
        parts = s.strip().split(":")
        if len(parts) != 3:
            return None
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, AttributeError):
        return None


def score_window(claimed: str | None, gt: dict) -> dict:
    """Did the agent find WHEN? Scored by overlap with the true injection window.

    Two numbers, because one hides the failure modes:
      recall    how much of the real incident the claimed range covers. Low = missed it.
      precision how much of the claimed range is really incident. Low = claimed half the
                trace and happened to contain the answer, which is not a finding.
    IoU combines them. 'unknown' is recorded as an honest abstention, NOT scored as wrong -
    the schema tells the agent a wrong window is worse than an admitted gap, and the metric
    has to agree or the instruction is a lie.
    """
    f = gt.get("fault") or {}
    t0 = _clock_s((f.get("injection_start_utc") or "").split("T")[-1].rstrip("Z"))
    t1 = _clock_s((f.get("injection_end_utc") or "").split("T")[-1].rstrip("Z"))
    out = {"claimed": claimed, "true_window": None, "iou": None,
           "recall": None, "precision": None, "verdict": None}
    if t0 is None or t1 is None or t1 <= t0:
        out["verdict"] = "ground truth window unreadable"
        return out
    out["true_window"] = "%s - %s" % (f.get("injection_start_utc"), f.get("injection_end_utc"))

    if not claimed or claimed.strip().lower() in ("unknown", "n/a", "none", ""):
        out["verdict"] = "abstained"
        return out
    m = re.split(r"\s*(?:-|to|–|—)\s*", claimed.strip())
    if len(m) != 2:
        out["verdict"] = "unparseable"
        return out
    c0, c1 = _clock_s(m[0]), _clock_s(m[1])
    if c0 is None or c1 is None or c1 <= c0:
        out["verdict"] = "unparseable"
        return out

    inter = max(0.0, min(t1, c1) - max(t0, c0))
    union = max(t1, c1) - min(t0, c0)
    out["recall"] = round(inter / (t1 - t0), 3)
    out["precision"] = round(inter / (c1 - c0), 3)
    out["iou"] = round(inter / union, 3) if union > 0 else 0.0
    out["verdict"] = ("hit" if out["iou"] >= 0.5 else
                      "partial" if inter > 0 else "miss")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="noisy_neighbor")
    ap.add_argument("--arm", default="given", choices=["given", "none"])
    ap.add_argument("--ask", default="hint", choices=["hint", "nohint"])
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--incident", type=int, default=0,
                    help="which incident of the family, 0-based. The matrix runs "
                         "several per problem, so a cell has to be able to name one.")
    ap.add_argument("--data-root", default="/scratch/yuvraj17/stratatrace/data/stratatrace-v2")
    ap.add_argument("--out-dir", default="/scratch/yuvraj17/stratatrace/results/q2")
    ap.add_argument("--packs-root", default="/scratch/yuvraj17/stratatrace/data/packs")
    ap.add_argument("--skills-dir", default=os.path.join(ROOT, "agentic-rca", "skills-generated"))
    # 14 was tuned when the agent had 7 pre-aggregated tools and a pack that pre-located the
    # incident. It now starts with neither: it must orient, sweep a timeline to find a change
    # point, confirm it against a second event, then compare ranges it picks itself - on files
    # holding ~20 million events. Each of those is a step, several are slow, and a run that
    # hits the cap mid-investigation scores as a failure of the agent when it was a failure of
    # the budget. 60 is deliberately generous for the pilot; measure what is actually used and
    # tighten it afterwards rather than guessing now.
    ap.add_argument("--max-steps", type=int, default=60)
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except Exception:
        pass

    import q2_harness as Q
    import config, agent, runs as R, skillreg
    from stratatrace import load_run

    prob = Q.PROBLEMS[args.problem]
    print("== cell ==")
    print("  problem   %s" % args.problem)
    print("  blueprint %s" % (prob["blueprint"] if args.arm == "given" else "(none - control arm)"))
    print("  ask       %s" % args.ask)
    print("  model     %s / %s" % (config.PROVIDER, config.model_id()))
    print("  rank_k    %d   narrowed at top-%d" % (Q.RANK_K, Q.NARROW_AT))

    incs = Q.incidents_for(args.problem, args.data_root, args.incident + 1)
    if len(incs) <= args.incident:
        print("no incident %d for %s under %s (found %d)"
              % (args.incident, args.problem, args.data_root, len(incs)))
        return 1
    inc = incs[args.incident]
    print("  incident  %s (%s)" % (inc["run_id"], inc["app"]))

    # the blueprint, handed over rather than selected
    skills = None
    if args.arm == "given":
        want = prob["blueprint"]
        allsk = skillreg.load_skills(args.skills_dir, strict=False)
        match = [s for s in allsk if s.name == want or want in s.name]
        if not match:
            print("  blueprint %r not found among: %s" % (want, [s.name for s in allsk]))
            return 1
        skills = [match[0]]
        print("  skill body %d chars" % len(match[0].body))

    # NO L0 PACK. Deliberate, and the core of the experiment.
    #
    # The pack is built by slicing the trace at ground_truth.json's injection_start_utc: every
    # figure in it is "baseline window vs incident window". Handing it over does not merely
    # leak WHEN the fault was - it pre-frames the whole analysis around the right window, so
    # the agent is describing an anomaly somebody already isolated rather than finding one.
    #
    # A real engineer gets a trace and knows none of that. So the agent gets the tools and
    # nothing else: ctf_timespan to orient, ctf_timeline to hunt for a change point, query_ctf
    # to inspect ranges it chooses, plus the trace/topology/log/metric/kernel queries. It has
    # to work out what happened, when, and where - with a blueprint and without one. That
    # comparison is the research question; anything that pre-locates the incident destroys it.
    print("  l0 pack   NOT GIVEN - agent must find the incident window itself")

    outd = Q.cell_dir(args.out_dir, args.problem, inc["run_id"], args.ask, args.arm, args.repeat)
    os.makedirs(outd, exist_ok=True)

    run = load_run(inc["run_dir"])
    t0 = time.time()
    dx = agent.diagnose(
        run, app=inc["app"], max_steps=args.max_steps,
        transcript_path=os.path.join(outd, "transcript.jsonl"),
        condition="q2|%s|%s" % (args.ask, args.arm),
        meta={"problem": args.problem, "arm": args.arm, "ask": args.ask, "repeat": args.repeat},
        skills=skills, skill_given=(args.arm == "given"), rank_k=Q.RANK_K,
        problem_hint=(prob["hint"] if args.ask == "hint" else None),
        kernel_only=True,          # phase 1: raw kernel traces only, no logs/metrics/spans
    )
    wall = round(time.time() - t0, 1)

    gt = json.load(open(os.path.join(inc["run_dir"], "ground_truth.json")))

    # BUG 4, found by the second pilot. R.score reads gt["target_service"], but in a bundle it
    # lives at gt["fault"]["target_service"] - so it was being handed the wrong level and saw
    # an empty target. That is not a harmless miss: measured, _svc_match against "" behaves
    # exactly as if the target were "host". noisy_neighbor's target IS host, so the pilot family
    # scored correctly by accident, while every problem with a real service target - catalogue,
    # carts, the rest - would have marked a CORRECT answer wrong. It would have surfaced only
    # after the full matrix, as "blueprints do not help localisation".
    gtf = gt.get("fault") or gt

    # BUG 5, same run. diagnose() returns `ranked_services` and `ranked_candidates`; the old
    # code asked for `ranked`, which does not exist, so every alternative was silently dropped.
    # On this run that threw away a rank-2 candidate naming the correct service.
    ranked_all = dx.get("ranked_candidates") or []
    dxd = dict(dx.get("diagnosis") or {})
    if ranked_all:
        dxd["_candidates"] = ranked_all      # R.score reads this for the per-axis rank metrics
    score = R.score(dxd, gtf, family=args.problem, ranked=dx.get("ranked_services"))

    # WINDOW ACCURACY - new, and half the task now that the agent is not told when.
    # Scored by overlap against the true injection window. Ground truth is read HERE, in the
    # scorer, which is the only place it belongs - never in a tool the agent can reach.
    win = score_window((dx.get("diagnosis") or {}).get("incident_window"), gt)

    # ranked_candidates puts the PRIMARY first, so the alternatives are everything after it.
    cands = ranked_all[1:]
    n_cand = len(ranked_all) or 1

    # BUG 3, found by the first pilot run, and the one that would have quietly ruined the
    # results. `rank` must mean "position of the CORRECT answer in the candidate list", and
    # nothing else. The old fallback chain let a wrong answer come out as rank 1, which scored
    # set_f1 = 1.0 and mrr = 1.0 on a run where both_ok was False.
    rank = None
    if score.get("both"):
        rank = 1                                   # primary verdict was right
    else:
        want_svc, want_fault = gtf.get("target_service"), gtf.get("name")
        for i, c in enumerate(cands, start=2):     # alternatives start at position 2
            if R._svc_match(c.get("service", ""), want_svc) and \
               R._fault_match(want_fault, args.problem, c.get("fault_type", "")):
                rank = i
                break
    row = {
        "problem": args.problem, "run_id": inc["run_id"], "app": inc["app"],
        "arm": args.arm, "ask": args.ask, "repeat": args.repeat,
        "model": config.model_id(), "provider": config.PROVIDER,
        "service_ok": score.get("service_hit"), "fault_ok": score.get("fault_hit"),
        "both_ok": score.get("both"), "no_answer": score.get("no_answer"),
        "rank": rank, "n_candidates": n_cand,
        "hit_at_k": bool(rank and rank <= Q.RANK_K),
        "narrowed": bool(rank and rank <= Q.NARROW_AT),
        "set_f1": Q.set_f1(bool(rank and rank <= Q.RANK_K), n_cand),
        "mrr": round(1.0 / rank, 3) if rank else 0.0,
        # BUG 2: diagnose returns tokens as {"in": .., "out": ..}, not flat in_tokens/out_tokens,
        # so the old read gave 0 on every run and the cost column would have been empty.
        "seconds": wall, "calls": dx.get("n_tool_calls"),
        "tokens_in": (dx.get("tokens") or {}).get("in", 0),
        "tokens_out": (dx.get("tokens") or {}).get("out", 0),
        "tokens": ((dx.get("tokens") or {}).get("in", 0)
                   + (dx.get("tokens") or {}).get("out", 0)),
        "true_fault": (gt.get("fault") or {}).get("name"),
        "true_service": (gt.get("fault") or {}).get("target_service"),
        "pred_fault": (dx.get("diagnosis") or {}).get("fault_type"),
        "pred_service": (dx.get("diagnosis") or {}).get("root_cause_service"),
        "window_claimed": (dx.get("diagnosis") or {}).get("incident_window"),
        "window_evidence": (dx.get("diagnosis") or {}).get("window_evidence"),
        "window_iou": win.get("iou"), "window_recall": win.get("recall"),
        "window_precision": win.get("precision"), "window_verdict": win.get("verdict"),
        "window_true": win.get("true_window"),
        "error": dx.get("error"),
    }

    json.dump(dx.get("diagnosis") or {}, open(os.path.join(outd, "diagnosis.json"), "w"), indent=1)
    json.dump(row, open(os.path.join(outd, "score.json"), "w"), indent=1)
    json.dump(gt, open(os.path.join(outd, "ground_truth.json"), "w"), indent=1)
    if skills:
        open(os.path.join(outd, "blueprint.md"), "w", encoding="utf-8").write(skills[0].body)
    if cands:
        json.dump(cands, open(os.path.join(outd, "ranked.json"), "w"), indent=1)

    print("\n== what the agent answered ==")
    d = dx.get("diagnosis") or {}
    print("  service    %s   (true: %s)" % (row["pred_service"], row["true_service"]))
    print("  fault      %s   (true: %s)" % (row["pred_fault"], row["true_fault"]))
    print("  confidence %s" % d.get("confidence"))
    print("  evidence   %s" % str(d.get("evidence"))[:240])
    print("  ranked     %d candidate(s)" % len(cands))
    for i, c in enumerate(cands[:5], 1):
        print("     %d. %-18s %-22s %s" % (i, c.get("service"), c.get("fault_type"),
                                           str(c.get("evidence"))[:70]))

    print("\n== WHEN - did it find the window? (it was never told) ==")
    print("  claimed   %s" % row["window_claimed"])
    print("  true      %s" % row["window_true"])
    print("  verdict   %s   IoU=%s recall=%s precision=%s"
          % (row["window_verdict"], row["window_iou"], row["window_recall"],
             row["window_precision"]))
    print("  why       %s" % str(row["window_evidence"])[:200])

    print("\n== metrics collected ==")
    for k in ("service_ok", "fault_ok", "both_ok", "rank", "n_candidates", "hit_at_k",
              "narrowed", "set_f1", "mrr", "window_iou", "window_verdict",
              "seconds", "calls", "tokens", "error"):
        print("  %-16s %s" % (k, row[k]))

    print("\n== files written ==")
    for f in sorted(os.listdir(outd)):
        print("  %-20s %8d bytes" % (f, os.path.getsize(os.path.join(outd, f))))
    print("\n  %s" % outd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
