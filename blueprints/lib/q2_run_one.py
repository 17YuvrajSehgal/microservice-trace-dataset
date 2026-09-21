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
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="noisy_neighbor")
    ap.add_argument("--arm", default="given", choices=["given", "none"])
    ap.add_argument("--ask", default="hint", choices=["hint", "nohint"])
    ap.add_argument("--repeat", type=int, default=1)
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

    incs = Q.incidents_for(args.problem, args.data_root, 1)
    if not incs:
        print("no incident found for %s under %s" % (args.problem, args.data_root))
        return 1
    inc = incs[0]
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
    )
    wall = round(time.time() - t0, 1)

    gt = json.load(open(os.path.join(inc["run_dir"], "ground_truth.json")))
    score = R.score(dx.get("diagnosis") or {}, gt, family=args.problem,
                    ranked=dx.get("ranked"))

    cands = dx.get("ranked") or []
    # the primary verdict is candidate 1; `ranked` holds the alternatives after it
    n_cand = 1 + len(cands)

    # BUG 3, found by the first pilot run, and the one that would have quietly ruined the
    # results. `rank` must mean "position of the CORRECT answer in the candidate list", and
    # nothing else. The old fallback chain let a wrong answer come out as rank 1, which scored
    # set_f1 = 1.0 and mrr = 1.0 on a run where both_ok was False.
    rank = None
    if score.get("both"):
        rank = 1                                   # primary verdict was right
    else:
        gtf = (gt.get("fault") or {})
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

    print("\n== metrics collected ==")
    for k in ("service_ok", "fault_ok", "both_ok", "rank", "n_candidates", "hit_at_k",
              "narrowed", "set_f1", "mrr", "seconds", "calls", "tokens", "error"):
        print("  %-14s %s" % (k, row[k]))

    print("\n== files written ==")
    for f in sorted(os.listdir(outd)):
        print("  %-20s %8d bytes" % (f, os.path.getsize(os.path.join(outd, f))))
    print("\n  %s" % outd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
