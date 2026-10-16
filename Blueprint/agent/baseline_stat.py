#!/usr/bin/env python3
"""Statistical / heuristic RCA baseline (RCA approach #1 of the 3-method comparison).

Deterministic rules over the SAME four tools the LLM agent uses (metrics change-points + trace
latency + log error-storms + kernel deviations) → the identical output contract
    { root_cause_service, fault_type, evidence, confidence }
No LLM, no API key. Same interface as agent.diagnose(run, app) so the evaluation runner treats the
two methods identically. By design it is strong on resource faults (cpu/mem/disk/net, throttling,
error storms — visible in metrics/logs) and WEAK on the kernel-decisive blind-spot faults
(slow_db / dependency_outage / noisy_neighbor) — that gap vs the kernel-aware agent is itself a
result (the "kernel as safety net" thesis, RQ3)."""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import RunTools


def _movers_by(movers, signal, min_rel=0.4):
    return [m for m in movers if m.get("signal") == signal
            and (m.get("incident") or 0) > 0 and abs(m.get("rel_change") or 0) >= min_rel]


def _decide(t: RunTools):
    metrics, mb = t.metrics()
    traces, tb = t.traces()
    logs, lb = t.logs()
    kernel, kb = t.kernel()
    movers = metrics.get("top_movers", []) if isinstance(metrics, dict) else []
    traces = traces if isinstance(traces, dict) else {}
    logs = logs if isinstance(logs, dict) else {}
    touched = mb + tb + lb + kb

    # ---- A. injected stress / neighbor container (host-level resource faults) ------------
    # movers are pre-ranked by magnitude, so the FIRST entry for a stress container is its
    # dominant signal → classify the fault by that.
    sm = next((m for m in movers
               if any(k in (m["container"] or "") for k in ("stress", "neighbor", "aggressor"))), None)
    if sm:
        stress, dom = sm["container"], sm.get("signal", "")
        if "neighbor" in stress:
            ft = "noisy_neighbor"
        elif "mem" in dom:
            ft = "memory_pressure"
        elif "fs" in dom:
            ft = "disk_io"
        elif "net" in dom:
            ft = "network_latency"
        else:
            ft = "cpu_saturation"
        return stress, ft, 0.8, f"injected '{stress}' dominant signal '{dom}'", touched

    # ---- B. per-service CPU throttling (svc_cpu_cap) --------------------------------------
    thr = _movers_by(movers, "cpu_throttled_s/s")
    if thr:
        c = thr[0]["container"]
        return c, "cpu_throttling", 0.78, f"'{c}' CFS-throttled ({thr[0]['incident']}/s)", touched

    # ---- C. error storm vs dependency outage (both raise errors) -------------------------
    err = sorted(((k, v.get("errors", 0)) for k, v in logs.items() if isinstance(v, dict)),
                 key=lambda kv: -kv[1])
    # trace timeouts: a caller stuck near a client timeout (~seconds) → points at a dead dependency
    timeouts = [s for s, v in traces.items() if isinstance(v, dict) and (v.get("p95_ms") or 0) >= 8000]
    if err and err[0][1] >= 40:
        top_err = err[0][0].replace("docker-compose_", "").replace("trainticket_", "").rstrip("_1")
        if timeouts:
            # dependency outage: the culprit is the timed-out edge's downstream — approximate by the
            # slowest service (its dependency is dark). Prefer a non-erroring slow service.
            culprit = max(traces.items(), key=lambda kv: (kv[1] or {}).get("p95_ms") or 0)[0]
            return culprit, "dependency_outage", 0.55, \
                f"callers time out (p95≥8s) at {timeouts[:3]}; a downstream dependency is dark", touched
        return top_err, "error_storm", 0.7, f"'{top_err}' logs {err[0][1]} errors, responses fast", touched

    # ---- D. slow_db: DB-path latency (metrics blind) — best-effort from traces+kernel ----
    #   elevated service latency + DB kernel deviations, no resource mover → likely DB slowness.
    if traces:
        slowest, sv = max(traces.items(), key=lambda kv: (kv[1] or {}).get("p95_ms") or 0)
        p95 = (sv or {}).get("p95_ms") or 0
        db = next((s for s in (kernel or {}) if isinstance(kernel, dict)
                   and any(k in s for k in ("db", "mysql", "mongo", "redis"))), None)
        if p95 >= 1000 and db:
            return db, "db_latency", 0.5, f"elevated latency (p95 {p95:.0f}ms) with DB kernel deviations on '{db}'", touched
        if p95 >= 1000:
            return slowest, "db_latency", 0.35, f"'{slowest}' slowest (p95 {p95:.0f}ms), no resource mover", touched

    # ---- E. fallback: strongest single metric mover -------------------------------------
    if movers:
        m = movers[0]
        return m["container"], "cpu_saturation", 0.25, f"weak: top mover {m['signal']} on '{m['container']}'", touched
    return None, "normal", 0.1, "no clear anomaly signal", touched


def diagnose(run, app: str | None = None, **_) -> dict:
    """Same return shape as agent.diagnose so evaluate.py handles both methods uniformly."""
    t = RunTools(run, app=app)
    svc, ft, conf, ev, touched = _decide(t)
    diagnosis = None if svc is None and ft == "normal" and conf <= 0.1 else \
        {"root_cause_service": svc, "fault_type": ft, "evidence": ev, "confidence": conf}
    # a fixed 4-tool "trajectory" (the baseline always reads all four once)
    traj = [{"step": 0, "tool": tool, "service": None} for tool in
            ("query_metrics", "query_traces", "query_logs", "query_kernel")]
    return {"run_id": os.path.basename(run.run_dir), "diagnosis": diagnosis, "trajectory": traj,
            "n_tool_calls": 4, "bytes_touched": touched, "tokens": {"in": 0, "out": 0},
            "model": "statistical-baseline", "wall_s": 0.0}


if __name__ == "__main__":
    from stratatrace import load_run
    rd = sys.argv[1]
    import json
    out = diagnose(load_run(rd), app=os.environ.get("STRATATRACE_APP"))
    gt = load_run(rd).ground_truth.get("fault", {})
    print(json.dumps(out["diagnosis"], indent=2))
    print("GT:", gt.get("target_service"), "/", gt.get("family"))
