#!/usr/bin/env python3
"""E2: controlled ablation of the agent's memory pipeline.

Each cell is one agent run in its own SUBPROCESS, so the harness's module-level state
cannot leak between cells and each cell gets its own ABL_* environment. Resumable:
a cell whose result file already exists is skipped.

    python nier-2027/run_campaign.py --plan            # show the cells, run nothing
    python nier-2027/run_campaign.py --limit 1         # smoke test
    python nier-2027/run_campaign.py --jobs 3          # full campaign
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT = ROOT / "Blueprint" / "agent"
INDEX = ROOT / "nier-2027" / "ctf-index"
OUT = ROOT / "nier-2027" / "results"
TRANS = ROOT / "nier-2027" / "transcripts"

HINT = "the coding task on this machine took noticeably longer than usual to finish"

RUNS = ROOT / "Blueprint/latency/1_svc_cpu_cap/agentic-os-noise/runs"
T4 = ROOT / "agentic-runs/2_threads_vs_cores/runs"

# Fault classes. The mechanism predicts the S1 defect costs little on a culprit that
# SPAWNS mid-trace and a lot on one that was already running.
CLASSES = {
    "resident": [RUNS / f"t3_implement_cap25_r{i}" for i in range(1, 6)],   # agent throttled
    "spawned":  [T4 / f"t4_w16_r{i}" for i in range(1, 6)],                 # workers launched
    "healthy":  [RUNS / f"t3_implement_nocap_r{i}" for i in range(1, 6)],   # negative control
}

# Only the knob under test moves. Empty dict == the shipped, repaired agent.
CONFIGS = {
    "repair":     {},
    "s1_deliver": {"ABL_FLAT_CAP": "2000"},        # v1 prefix-slice; 2000 binds on these
                                                   # traces as 6000 did on microservice ones
                                                   # (DESIGN.md amendment A2)
    "s2_steps":   {"ABL_WORKER_STEPS": "12"},      # the measured wall
    "s3_thread":  {"ABL_THREAD_BUDGET": "80000"},  # the old within-phase budget
    "s4_transfer": {"ABL_NO_COMPUTED": "1"},       # voluntary note_finding only
    "all_defect": {"ABL_FLAT_CAP": "2000", "ABL_WORKER_STEPS": "12",
                   "ABL_THREAD_BUDGET": "80000", "ABL_NO_COMPUTED": "1"},
}

# (config, class, repeats). Priority order: the headline interaction first, so a
# truncated campaign still answers H2.
PLAN = [
    ("repair",      "resident", 3), ("s1_deliver", "resident", 3),   # H2 core
    ("repair",      "spawned",  3), ("s1_deliver", "spawned",  3),   # H2 core
    ("s4_transfer", "resident", 3),                                   # H3
    ("all_defect",  "resident", 3),
    ("s2_steps",    "resident", 2), ("s3_thread",  "resident", 2),
    ("repair",      "healthy",  1), ("all_defect", "healthy",  1),
]


def cells():
    out = []
    for cfg, klass, reps in PLAN:
        for rd in CLASSES[klass]:
            for rep in range(1, reps + 1):
                out.append({"config": cfg, "klass": klass, "run": rd.name,
                            "run_dir": str(rd), "rep": rep,
                            "cell": f"{cfg}__{klass}__{rd.name}__r{rep}"})
    return out


def load_dotenv() -> dict:
    """Parse .env. Strips inline '#' comments on unquoted values - RCA_PROVIDER has one."""
    env = {}
    p = ROOT / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) > 1:
            v = v[1:-1]
        else:
            v = v.split("#", 1)[0].strip()
        env[k.strip()] = v
    return env


def run_cell(c: dict, base: dict, timeout: int) -> dict:
    res_path = OUT / (c["cell"] + ".json")
    if res_path.exists():
        return {**c, "status": "skipped"}

    env = dict(os.environ)
    env.update(base)
    env.update(CONFIGS[c["config"]])
    env["CTF_INDEX_ROOT"] = str(INDEX)
    env["RCA_TRANSCRIPT"] = str(TRANS / (c["cell"] + ".json"))
    env["PYTHONIOENCODING"] = "utf-8"

    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "agent_v2.py", c["run_dir"],
                            "--hint", HINT],
                           cwd=str(AGENT), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        rec = {**c, "status": "timeout", "wall_s": round(time.time() - t0, 1)}
        res_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec

    out = (p.stdout or "").strip()
    rec = {**c, "status": "ok" if p.returncode == 0 else "error",
           "returncode": p.returncode, "wall_s": round(time.time() - t0, 1),
           "env_ablation": CONFIGS[c["config"]]}
    try:
        rec["result"] = json.loads(out[out.index("{"):]) if "{" in out else None
    except Exception as e:
        rec["status"] = "unparseable"
        rec["parse_error"] = f"{type(e).__name__}: {e}"
        rec["stdout_tail"] = out[-1500:]
    if p.returncode != 0:
        rec["stderr_tail"] = (p.stderr or "")[-2000:]
    res_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only-config")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--timeout", type=int, default=2400)
    a = ap.parse_args()

    cs = cells()
    if a.only_config:
        cs = [c for c in cs if c["config"] == a.only_config]
    if a.limit:
        cs = cs[:a.limit]

    if a.plan:
        from collections import Counter
        print(f"{len(cs)} cells\n")
        for (cfg, kl), n in Counter((c["config"], c["klass"]) for c in cs).items():
            print(f"  {cfg:12} {kl:9} {n:>3} cells")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    TRANS.mkdir(parents=True, exist_ok=True)
    base = load_dotenv()
    missing = [k for k in ("RCA_PROVIDER",) if not base.get(k)]
    if missing:
        print(f"missing from .env: {missing}", file=sys.stderr)
        return 2
    print(f"provider={base.get('RCA_PROVIDER')} model={base.get('RCA_MODEL')} "
          f"cells={len(cs)} jobs={a.jobs}\n", flush=True)

    t0, done = time.time(), 0
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_cell, c, base, a.timeout): c for c in cs}
        for f in cf.as_completed(futs):
            r = f.result(); done += 1
            dx = (r.get("result") or {}).get("diagnosis") or {}
            tok = (r.get("result") or {}).get("tokens") or {}
            print(f"[{done:>3}/{len(cs)}] {r['status']:<11} {r['cell']:<52} "
                  f"{r.get('wall_s',0):>6.0f}s  in={tok.get('in',0):>8,}  "
                  f"{str(dx.get('fault_type','-'))[:18]:<18} "
                  f"conf={dx.get('confidence','-')}", flush=True)
    print(f"\n{done} cells in {(time.time()-t0)/60:.0f} min -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
