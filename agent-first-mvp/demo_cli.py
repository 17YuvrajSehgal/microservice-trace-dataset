#!/usr/bin/env python3
"""Deterministic CLI — the robust demo spine (no MCP / no agent required).

    python demo_cli.py discover "my database is slow"
    python demo_cli.py phase1   db-slowness-rca
    python demo_cli.py run      db-slowness-rca          # replay on registered run
    python demo_cli.py run      db-slowness-rca --live    # live scoped capture (if available)

Every `run` writes result.json + a self-contained dashboard HTML under ~/mvp_work/results/.
This path never touches the dataset except read-only. Stdlib only.
"""
import argparse, glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "engine"))
import phase2, rca
from dashboard import render as dash

SKILLS_DIR = os.path.join(HERE, "skills")
RESULTS = os.path.expanduser("~/mvp_work/results")

def _exp(p): return os.path.expanduser(p) if p else p
def load_runs(): return json.load(open(os.path.join(HERE, "runs.json")))
def skill_path(name): return os.path.join(SKILLS_DIR, name, "skill.json")
def load_skill(name): return json.load(open(skill_path(name)))

def all_skills():
    out = []
    for p in sorted(glob.glob(os.path.join(SKILLS_DIR, "*", "skill.json"))):
        out.append(json.load(open(p)))
    return out

def discover(problem):
    p = problem.lower(); ranked = []
    for s in all_skills():
        hits = sum(1 for t in s.get("problem_triggers", []) if any(w in p for w in t.lower().split()))
        exact = any(t.lower() in p for t in s.get("problem_triggers", []))
        score = (10 if exact else 0) + hits
        if score: ranked.append((score, s))
    ranked.sort(key=lambda x: -x[0])
    return [{"skill": s["skill"], "score": sc, "decisive_modality": s.get("decisive_modality"),
             "fault_source": s.get("fault_source")} for sc, s in ranked]

def phase1(name):
    return phase2.phase1(load_skill(name))

def execute(name, live=False, run_dir=None, kernel=None, problem=None, max_seconds=None):
    """Core: resolve registry, run phase-2, write result.json + dashboard. Returns the
    result dict. NO stdout printing (safe to call from the MCP stdio server)."""
    skill = load_skill(name); fs = skill.get("fault_source")
    reg = load_runs().get(fs, {})
    run_dir = _exp(run_dir or reg.get("run_dir"))
    kernel = _exp(kernel or reg.get("kernel_dir"))
    problem = problem or reg.get("problem")
    max_seconds = max_seconds if max_seconds is not None else reg.get("max_seconds", 60)
    if live:
        import importlib.util
        lc = os.path.join(HERE, "live_capture.py")
        if os.path.exists(lc):
            spec = importlib.util.spec_from_file_location("live_capture", lc)
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
            run_dir, kernel = m.capture(skill)   # blocks; returns fresh paths
    if not run_dir or not os.path.exists(run_dir):
        raise FileNotFoundError(f"no run for fault '{fs}' (looked at {run_dir}); register it in runs.json")
    tag = f"{name}-live" if live else name          # keep live outputs distinct from the replay ones
    out_json = os.path.join(RESULTS, f"{tag}.json")
    res = phase2.run(skill_path(name), run_dir, kernel, problem, max_seconds,
                     mode=("live" if live else "replay"), out_path=out_json)
    res["dashboard_html"] = os.path.join(RESULTS, f"{tag}.html")
    open(res["dashboard_html"], "w", encoding="utf-8").write(dash.full_page(res))
    return res

def run(name, live=False, run_dir=None, kernel=None, problem=None, max_seconds=None):
    try:
        res = execute(name, live, run_dir, kernel, problem, max_seconds)
    except FileNotFoundError as ex:
        print(f"[!] {ex}", file=sys.stderr); sys.exit(2)
    out_html = res["dashboard_html"]; v = res["verdict"]
    print(f"\n  PROBLEM   {res['problem_statement']}")
    print(f"  SKILL     {name}  ({res['mode']})")
    print(f"  ROOT CAUSE {v['root_cause']}")
    print(f"  DECISIVE  {v['decisive_modality']}   CONFIDENCE {v['confidence']}")
    print(f"  RULED OUT " + " | ".join(v.get("ruled_out", [])))
    print(f"  DATA      {v.get('data_touched_mb')} MB vs {v.get('everything_bundle_mb')} MB  ({v.get('reduction_x')}x less)")
    print(f"  CORRECT   {res['correct']}   (ground truth: {res['ground_truth']['fault']['name']})")
    print(f"  DASHBOARD {out_html}\n")
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover"); d.add_argument("problem")
    p = sub.add_parser("phase1"); p.add_argument("skill")
    r = sub.add_parser("run"); r.add_argument("skill"); r.add_argument("--live", action="store_true")
    r.add_argument("--run-dir"); r.add_argument("--kernel"); r.add_argument("--problem"); r.add_argument("--max-seconds", type=int)
    a = ap.parse_args()
    if a.cmd == "discover": print(json.dumps(discover(a.problem), indent=2))
    elif a.cmd == "phase1": print(json.dumps(phase1(a.skill), indent=2))
    elif a.cmd == "run": run(a.skill, a.live, a.run_dir, a.kernel, a.problem, a.max_seconds)
