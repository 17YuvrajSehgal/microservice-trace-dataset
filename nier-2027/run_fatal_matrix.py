#!/usr/bin/env python3
"""E3: the fatal-case mini-matrix, launched only if the given+repair probe commits.

given arm (service-cpu-throttle skill, frontmatter stripped) x {repair, defect at
the DEPLOYED 6000 cap} x 5 repeats, on the real 21-container run. Subprocess per
cell for env isolation; resumable.

    python nier-2027/run_fatal_matrix.py [--jobs 2]
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "nier-2027" / "results-fatal"
ARMS = {"repair": {}, "defect": {"ABL_FLAT_CAP": "6000"}}
REPS = 5


def run_cell(arm: str, rep: int, timeout: int) -> dict:
    cell = f"given_{arm}_r{rep}"
    rp = OUT / (cell + ".json")
    if rp.exists():
        return {"cell": cell, "status": "skipped"}
    env = dict(os.environ)
    env.update(ARMS[arm])
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(ROOT / "nier-2027" / "probe_given.py"),
             f"m{rep}"] + (["defect"] if arm == "defect" else []),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env)
        out = (p.stdout or "").strip()
        rec = {"cell": cell, "arm": arm, "rep": rep,
               "status": "ok" if p.returncode == 0 else "error",
               "wall_s": round(time.time() - t0, 1)}
        try:
            rec["result"] = json.loads(out[out.index("{"):])
        except Exception:
            rec["status"] = "unparseable"
            rec["stdout_tail"] = out[-1200:]
            rec["stderr_tail"] = (p.stderr or "")[-800:]
    except subprocess.TimeoutExpired:
        rec = {"cell": cell, "arm": arm, "rep": rep, "status": "timeout",
               "wall_s": round(time.time() - t0, 1)}
    rp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=2400)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cells = [(arm, rep) for arm in ARMS for rep in range(1, REPS + 1)]
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(run_cell, arm, rep, a.timeout) for arm, rep in cells]
        for f in cf.as_completed(futs):
            r = f.result()
            res = (r.get("result") or {})
            print(f"{r['status']:<11} {r['cell']:<20} {r.get('wall_s',0):>6.0f}s  "
                  f"rcs={str(res.get('rcs'))[:48]}  conf={res.get('conf')}",
                  flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
