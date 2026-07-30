#!/usr/bin/env python3
"""Phase-2 orchestrator: run a skill against a collected run (replay) or live capture.

Reads the skill's *scoped* requirements, gathers only the declared modalities
(byte-counted), runs the wait-attribution + trace/log/metric ops, scores a
deterministic verdict, and writes a result.json the dashboard renders.

READ-ONLY on ~/traces. Kernel CTF is read from a decompressed working copy
(~/mvp_work) passed via --kernel. Stdlib only.
"""
import argparse, json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
import wait_attribution as wa
import modalities as mod
import rca

KERNEL_NAMES = ["sched_switch","sched_waking","sched_wakeup","syscall_entry_","syscall_exit_"]

def _dir_mb(path):
    tot = 0
    for root, _, files in os.walk(path):
        for fn in files:
            try: tot += os.path.getsize(os.path.join(root, fn))
            except OSError: pass
    return round(tot/1e6, 1)

def phase1(skill):
    """Emit the machine-readable collection spec (the differentiator)."""
    req = skill.get("requirements", {})
    k = req.get("kernel_lttng", {})
    return {"skill": skill.get("skill"), "decisive_modality": skill.get("decisive_modality"),
            "hypotheses": [h.get("id") for h in skill.get("hypotheses", [])],
            "collection_spec": {
                "kernel": {"events": k.get("events"), "syscalls": k.get("syscalls"),
                           "scope": k.get("scope"), "mode": k.get("mode"),
                           "max_duration_s": k.get("max_duration_s"),
                           "capture_cmd": k.get("capture_cmd")},
                "otel": req.get("otel"), "logs": req.get("logs"), "metrics": req.get("metrics")}}

def gather_slow_db(skill, run_dir, kernel_dir, window, max_seconds):
    ev = {"kernel": {}, "spans": {}, "logs": {}, "metrics": {}}
    touched = 0
    # kernel wait-attribution: catalogue (subject) + catalogue-db (rule out DB disk)
    for svc in ("catalogue", "catalogue-db"):
        r = wa.attribute_run(run_dir, kernel_dir, svc, KERNEL_NAMES, max_seconds)
        touched += r.get("scoped_bytes", 0)
        ev["kernel"][svc] = {k: r[k] for k in ("rule_out_pct","verdict_hint","seconds",
                                               "n_tids_seen","scoped_bytes")}
    b, e = window
    sp, spb = mod.span_latency(os.path.join(run_dir,"otlp","spans.jsonl"), b, e, ["catalogue","front-end"])
    lg, lgb = mod.log_signals(os.path.join(run_dir,"logs"), ["catalogue"], b, e)
    mc, mcb = mod.metric_changepoint(run_dir)
    ev["spans"] = sp; ev["logs"] = lg; ev["metrics"] = mc
    touched += spb + lgb + mcb
    ev["data_touched_mb"] = round(touched/1e6, 2)
    return ev

def gather_generic(skill, run_dir, kernel_dir, window, max_seconds):
    """Fallback for non-slow_db skills: attribute each scoped service + spans/logs/metrics."""
    req = skill.get("requirements", {})
    svcs = (req.get("kernel_lttng", {}).get("scope", {}) or {}).get("target_services", [])
    ev = {"kernel": {}, "spans": {}, "logs": {}, "metrics": {}}; touched = 0
    for svc in svcs:
        if svc not in wa.SERVICE_COMM:  # skip java-shared comms in fallback
            continue
        r = wa.attribute_run(run_dir, kernel_dir, svc, KERNEL_NAMES, max_seconds)
        touched += r.get("scoped_bytes", 0)
        ev["kernel"][svc] = {k: r[k] for k in ("rule_out_pct","verdict_hint","seconds","n_tids_seen","scoped_bytes")}
    b, e = window
    otel_svcs = (req.get("otel", {}) or {}).get("services", [])
    if otel_svcs:
        sp, spb = mod.span_latency(os.path.join(run_dir,"otlp","spans.jsonl"), b, e, otel_svcs)
        ev["spans"] = sp; touched += spb
    log_svcs = (req.get("logs", {}) or {}).get("services", [])
    if log_svcs:
        lg, lgb = mod.log_signals(os.path.join(run_dir,"logs"), log_svcs, b, e); ev["logs"] = lg; touched += lgb
    mc, mcb = mod.metric_changepoint(run_dir); ev["metrics"] = mc; touched += mcb
    ev["data_touched_mb"] = round(touched/1e6, 2)
    return ev

GATHERERS = {"slow_db": gather_slow_db}

def run(skill_path, run_dir, kernel_dir, problem, max_seconds=0, mode="replay", out_path=None):
    skill = json.load(open(skill_path))
    gt = json.load(open(os.path.join(run_dir, "ground_truth.json")))
    win = [gt["fault"]["injection_start_utc"],
           wa._cap(gt["fault"]["injection_start_utc"], gt["fault"]["injection_end_utc"], max_seconds)]
    gather = GATHERERS.get(skill.get("fault_source"), gather_generic)
    ev = gather(skill, run_dir, kernel_dir, win, max_seconds)
    # size accounting: scoped (touched) vs what an *undirected* kernel-deep tool
    # would have to ingest for this run — the full decompressed kernel + all spans/logs.
    ev["on_disk_bundle_mb"] = _dir_mb(run_dir)                 # gzipped storage
    ev["undirected_processing_mb"] = round(_dir_mb(kernel_dir)  # full decompressed kernel
                                           + _dir_mb(os.path.join(run_dir, "otlp"))
                                           + _dir_mb(os.path.join(run_dir, "logs")), 1)
    ev["full_bundle_mb"] = ev["undirected_processing_mb"]      # headline denominator
    verdict = rca.decide(skill, ev)
    result = {
        "skill": skill.get("skill"), "fault_source": skill.get("fault_source"),
        "run": os.path.basename(run_dir), "mode": mode, "window": win,
        "problem_statement": problem or (skill.get("problem_triggers") or [""])[0],
        "phase1": phase1(skill),
        "evidence_bundle": ev,
        "verdict": verdict,
        "ground_truth": gt,   # oracle — dashboard shows as "actual"; not used by the reasoner
        "correct": verdict.get("winning_hypothesis") in
                   (skill.get("hypotheses", [{}])[0].get("id"), skill.get("fault_source")),
    }
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        json.dump(result, open(out_path, "w"), indent=2)
    return result

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--problem", default=None)
    ap.add_argument("--max-seconds", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = run(a.skill, a.run_dir, a.kernel, a.problem, a.max_seconds, out_path=a.out)
    # print without the huge ground_truth kernel echo
    slim = {k: res[k] for k in ("skill","run","problem_statement","verdict","correct")}
    print(json.dumps(slim, indent=2))
