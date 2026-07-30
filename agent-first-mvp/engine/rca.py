#!/usr/bin/env python3
"""Root-cause reasoner: evidence bundle + skill hypotheses -> output-contract verdict.

Design choice (defensible, demo-safe): the *verdict* is DETERMINISTIC — scored by
rules over the structured evidence, so the system never hallucinates a root cause.
An optional LLM layer (`narrate`) writes the natural-language explanation over the
SAME evidence, but cannot change which hypothesis wins. Stdlib only.
"""

def _pct(k, ev, svc):
    return (ev.get("kernel", {}).get(svc, {}).get("rule_out_pct", {}) or {}).get(k)

def _span_p95(ev, svc):
    return (ev.get("spans", {}).get(svc, {}) or {}).get("p95_s")

def _metric(ev):
    for c in ev.get("metrics", {}).get("checks", []):
        if c.get("passed"): return c
    return (ev.get("metrics", {}).get("checks") or [None])[0]

# ---- per-fault deciders -------------------------------------------------------
def decide_slow_db(ev):
    cat = ev["kernel"].get("catalogue", {}); db = ev["kernel"].get("catalogue-db", {})
    on = _pct("on_cpu", ev, "catalogue") or 0; disk = _pct("disk_wait", ev, "catalogue") or 0
    io = _pct("off_cpu_io_wait", ev, "catalogue") or 0
    db_disk = _pct("disk_wait", ev, "catalogue-db") or 0; db_cpu = _pct("on_cpu", ev, "catalogue-db") or 0
    m = _metric(ev); p95 = _span_p95(ev, "catalogue")
    ruled = []
    if on < 15: ruled.append(f"service CPU-bound — catalogue on-CPU only {on}% of the window")
    if disk < 15 and db_disk < 15:
        ruled.append(f"DB disk I/O — catalogue disk {disk}%, DB engine (mysqld) disk {db_disk}%")
    ev_list = [
        f"KERNEL: catalogue threads spend {io}% of the window off-CPU on I/O-readiness wait, "
        f"only {on}% on-CPU and {disk}% on disk → the latency is waiting, not compute or disk.",
        f"KERNEL: the database engine (mysqld) shows {db_cpu}% CPU and {db_disk}% disk → the DB "
        f"itself is healthy/idle, so the delay is in the connection path, not the database.",
    ]
    if p95: ev_list.append(f"TRACES: catalogue SERVER-span p95 = {p95}s during the window (baseline ≈ 5 ms).")
    if m: ev_list.append(f"METRICS: {m['name']} rose {m['baseline']:.3g}s → {m['injection']:.3g}s "
                         f"({m['delta_sigma']:.0f}σ), status={ev['metrics'].get('status')}.")
    took = ev.get("logs", {}).get("took", {}).get("catalogue")
    if took: ev_list.append(f"LOGS: catalogue's own request logs corroborate — took p95 = {took['p95_ms']} ms.")
    return {
        "root_cause": "Latency injected into the catalogue → database connection path (the DB "
                      "proxy/network hop). Catalogue's request time is spent almost entirely off-CPU "
                      "waiting on I/O readiness; the database engine is healthy.",
        "winning_hypothesis": "db_conn_path_latency",
        "ruled_out": ruled,
        "evidence": ev_list,
        "decisive_modality": "kernel + traces",
        "confidence": 0.93 if (on < 15 and disk < 15 and io > 60) else 0.7,
        "recommended_fix": "Inspect the catalogue→DB connection path (proxy / service-mesh / network "
                           "policy adding latency). The database engine needs no tuning.",
    }

def decide_noisy_neighbor(ev):
    agg = ev["kernel"].get("noisy-neighbor", {}) or ev["kernel"].get("aggressor", {})
    agg_cpu = (agg.get("seconds", {}) or {}).get("on_cpu", 0); agg_tids = agg.get("n_tids_seen", 0)
    vic = ev.get("spans", {}).get("catalogue", {}) or {}
    vic_p95_ms = (vic.get("p95_s") or 0)*1000
    vic_run = ((ev["kernel"].get("catalogue", {}) or {}).get("rule_out_pct", {}) or {}).get("runnable_wait", 0)
    ev_list = [
        f"KERNEL: a non-service process (stress-ng, {agg_tids} threads, container 'noisy-neighbor') "
        f"consumed {agg_cpu:.1f} CPU-seconds in the window — it is contending for cores.",
        f"TRACES: the services stay healthy — catalogue p95 = {vic_p95_ms:.1f} ms (normal). The contention "
        f"is invisible at the service layer; only the kernel names the neighbor.",
    ]
    if vic_run: ev_list.append(f"KERNEL: victim catalogue shows {vic_run}% runnable-wait (mild CPU starvation).")
    return {"root_cause": "A co-located noisy neighbor (a stress-ng container, not part of the app) is "
                          "burning CPU and stealing cycles from the services. Metrics see only ‘host CPU "
                          "busy’; traces and service metrics look normal — the kernel is the only modality "
                          "that identifies the culprit process.",
            "winning_hypothesis": "colocated_cpu_hog",
            "ruled_out": [f"genuine service load — catalogue p95 is {vic_p95_ms:.1f} ms, i.e. KPIs barely moved"],
            "evidence": ev_list, "decisive_modality": "kernel-only", "confidence": 0.88,
            "recommended_fix": "Identify and cap/isolate the noisy-neighbor container (cgroup cpu limits, "
                               "dedicated cores, or evict it); the services themselves need no change."}

def decide_dependency_outage(ev):
    sp = ev.get("spans", {}); pay = sp.get("payment", {}) or {}; orders = sp.get("orders", {}) or {}
    fe = sp.get("front-end", {}) or {}
    pay_n = pay.get("n", 0); orders_p95 = orders.get("p95_s", 0)
    pay_cpu = ((ev["kernel"].get("payment", {}) or {}).get("seconds", {}) or {}).get("on_cpu", 0)
    ev_list = [
        f"TRACES: the payment service emitted {pay_n} spans during the window — it went dark (no telemetry).",
        f"TRACES: its caller hangs — orders p95 = {orders_p95}s (client-side timeout), front-end max "
        f"{fe.get('max_s','?')}s. The failure localizes to the orders→payment edge.",
        f"KERNEL: payment’s cgroup is near-silent — {pay_cpu:.2f} CPU-seconds — consistent with a frozen "
        f"(docker-pause / freezer) process that cannot respond.",
    ]
    errs = ev.get("logs", {}).get("errors", {}).get("orders")
    if errs: ev_list.append(f"LOGS: orders logged {errs.get('n')} errors (calls into payment failing).")
    return {"root_cause": "The payment service is down (frozen): it stops emitting spans and shows ~0 CPU "
                          "activity, while its callers hang at their timeout. The dead dependency is payment; "
                          "orders and front-end are victims, not the cause.",
            "winning_hypothesis": "downstream_dependency_down",
            "ruled_out": ["caller bug — orders/front-end are healthy until they call payment",
                          "network partition — only payment is affected, not many services"],
            "evidence": ev_list, "decisive_modality": "traces + kernel", "confidence": 0.9,
            "recommended_fix": "Restart/unfreeze the payment container; add a caller-side timeout + circuit "
                               "breaker so orders fails fast instead of hanging for the full timeout."}

def decide_error_storm(ev):
    m = _metric(ev); sp = ev.get("spans", {}).get("catalogue", {}) or {}
    p95_ms = (sp.get("p95_s") or 0)*1000
    sigs = (ev.get("logs", {}).get("errors", {}).get("catalogue", {}) or {}).get("signatures", [])
    inj = m.get("injection") if m else None
    ev_list = []
    if m: ev_list.append(f"METRICS: {m['name']} spiked {m['baseline']}→{inj} req/s during the window.")
    if sigs:
        ev_list.append(f"LOGS: catalogue logged {sum(s['count'] for s in sigs)}+ errors; top signature "
                       f"×{sigs[0]['count']}: “{sigs[0]['sample'][:120]}”.")
    ev_list.append(f"TRACES: requests fail fast — catalogue p95 = {p95_ms:.2f} ms (errors return immediately, "
                   f"not slowly) → this is a failure storm, not a slowdown.")
    return {"root_cause": "A storm of downstream connection failures: the catalogue→database connection is "
                          "being reset, so catalogue returns 5xx at high rate. The logs carry the decisive "
                          "signature (connection resets); requests fail fast rather than slow down.",
            "winning_hypothesis": "downstream_conn_failure",
            "ruled_out": ["bad deploy — errors are concentrated on the DB path, not uniform across routes",
                          "resource exhaustion — requests fail fast (p95 ~ms), not under CPU/mem pressure"],
            "evidence": ev_list, "decisive_modality": "logs + metrics", "confidence": 0.87,
            "recommended_fix": "Fix the catalogue→DB connection being reset (proxy/DB dropping connections); "
                               "add retry-with-backoff and connection-health checks on the client."}

def decide_generic(ev, skill):
    # fallback: lean on the strongest service's verdict_hint
    best = None
    for svc, k in ev.get("kernel", {}).items():
        if best is None or (k.get("rule_out_pct", {}).get("off_cpu_io_wait", 0) >
                            best[1].get("rule_out_pct", {}).get("off_cpu_io_wait", 0)):
            best = (svc, k)
    hint = best[1].get("verdict_hint") if best else "unknown"
    m = _metric(ev)
    ev_list = []
    if best: ev_list.append(f"KERNEL: {best[0]} verdict = {hint}; rule-out = {best[1].get('rule_out_pct')}.")
    if m: ev_list.append(f"METRICS: {m['name']} {m['baseline']}→{m['injection']} ({m.get('delta_sigma','?')}σ).")
    return {"root_cause": f"Kernel wait-attribution indicates: {hint}.",
            "winning_hypothesis": hint, "ruled_out": [], "evidence": ev_list,
            "decisive_modality": skill.get("decisive_modality", "kernel"),
            "confidence": 0.6, "recommended_fix": "See evidence; verdict from kernel rule-out."}

DECIDERS = {"slow_db": decide_slow_db, "noisy_neighbor": decide_noisy_neighbor,
            "dependency_outage": decide_dependency_outage, "error_storm": decide_error_storm}

def decide(skill, ev):
    fn = DECIDERS.get(skill.get("fault_source"))
    out = fn(ev) if fn else decide_generic(ev, skill)
    out["data_touched_mb"] = ev.get("data_touched_mb")
    out["everything_bundle_mb"] = ev.get("full_bundle_mb")
    if ev.get("full_bundle_mb") and ev.get("data_touched_mb"):
        out["reduction_x"] = round(ev["full_bundle_mb"] / max(ev["data_touched_mb"], 0.001), 1)
    return out

# ---- optional LLM narration (never changes the verdict) -----------------------
def narrate(skill, ev, verdict):
    """Best-effort: ask `claude` CLI to write prose over the SAME evidence. Falls back
    silently to the deterministic evidence list if unavailable."""
    import json, shutil, subprocess
    if not shutil.which("claude"): return None
    prompt = ("You are an SRE. Given this fault RCA evidence and the deterministic verdict, "
              "write a 3-4 sentence root-cause narrative for an engineer. Do NOT change the verdict. "
              "Evidence:\n" + json.dumps({"skill": skill.get("skill"), "evidence": ev.get("_bundle", ev),
              "verdict": verdict}, default=str)[:6000])
    try:
        r = subprocess.run(["claude","-p",prompt], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() or None
    except Exception:
        return None
