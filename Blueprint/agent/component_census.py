#!/usr/bin/env python3
"""Component census (review item 1): why a deployment has more components than services.

For each app, list every container seen in a run and record which telemetry it produces:
request spans, application logs, container metrics, kernel activity. The point of the table
is that the span-less components (databases, brokers, caches, registries, proxies) are
exactly the ones the trace modality cannot point AT.

    python component_census.py [--out results/review/component_census.json]
"""
from __future__ import annotations
import argparse, json, os, re, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stratatrace import load_run
import runs as R
from tools import RunTools

KIND = [
    (r"(mysql|mariadb|mongo|postgres|-db$|_db$|-db_|redis)", "datastore"),
    (r"(rabbit|kafka|queue-master)", "message broker / consumer"),
    (r"(nacos|consul|eureka|registry)", "service registry"),
    (r"(edge-router|nginx|gateway|ingress|proxy|toxiproxy)", "proxy / ingress"),
    (r"(ui-dashboard|front-end)", "user-facing service"),
    (r"(prometheus|cadvisor|node-?exporter|otel|collector|grafana)", "our collection stack"),
    (r"(stress|neighbor|aggressor|anomaly)", "injected fault container"),
]


def kind_of(name: str) -> str:
    n = name.lower()
    for pat, k in KIND:
        if re.search(pat, n):
            return k
    return "business service"


def real_containers(run_dir: str) -> set:
    """Containers that were actually running, from the run's own docker snapshot.

    tools.services() unions names seen across every modality, which also picks up metric
    labels that are not containers at all (os version strings, scrape-job names). The
    meta/ container list is the authoritative roster, so the census is grounded on it."""
    import glob
    names = set()
    for f in sorted(glob.glob(os.path.join(run_dir, "meta", "container_list_*.txt"))):
        try:
            names |= {l.strip() for l in open(f) if l.strip()}
        except OSError:
            pass
    return names


def census(app: str, run_dir: str) -> list:
    run = load_run(run_dir)
    t = RunTools(run, app=app)
    roster = real_containers(run_dir)
    seen = set(t.services()) - {"host"}
    if roster:
        roster_n = {R._norm(x) for x in roster}
        # keep telemetry-visible names that map onto a real container, plus injected fault
        # containers (they are created mid-run, so an early snapshot can miss them)
        containers = {c for c in seen
                      if R._norm(c) in roster_n
                      or any(R._norm(c) in r or r in R._norm(c) for r in roster_n)
                      or re.search(r"(stress|neighbor|aggressor|anomaly)", c.lower())}
    else:
        containers = seen

    spans = run.spans()
    span_svcs = set()
    if hasattr(spans, "empty") and not spans.empty and "service" in spans.columns:
        span_svcs = {str(x) for x in spans["service"].dropna().unique()}

    logs = run.logs()
    log_svcs = defaultdict(int)
    if hasattr(logs, "empty") and not logs.empty:
        for c, n in logs.groupby("container").size().items():
            log_svcs[str(c)] = int(n)

    l1 = run.kernel_l1()
    kern = set()
    if hasattr(l1, "empty") and not l1.empty and "service" in l1.columns:
        kern = {str(x) for x in l1["service"].dropna().unique()}

    def norm(s):
        return R._norm(str(s))

    span_n, kern_n = {norm(s) for s in span_svcs}, {norm(s) for s in kern}
    log_n = {norm(k): v for k, v in log_svcs.items()}

    rows = []
    for c in sorted(containers):
        n = norm(c)
        rows.append({
            "app": app, "component": c, "kind": kind_of(c),
            "emits_spans": n in span_n,
            "log_lines": log_n.get(n, 0),
            "kernel_visible": n in kern_n,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/review/component_census.json")
    a = ap.parse_args()

    allrows = []
    for app in ("sockshop", "trainticket"):
        rec = next(iter(R.iter_runs(app)), None)
        if not rec:
            print(f"{app}: no runs"); continue
        rows = census(app, rec.dir)
        allrows += rows
        n_span = sum(r["emits_spans"] for r in rows)
        print(f"\n=== {app}: {len(rows)} components in one run ({rec.run_id}) ===")
        print(f"{'component':34s} {'kind':26s} spans  logs      kernel")
        for r in rows:
            print(f"  {r['component']:32s} {r['kind']:26s} "
                  f"{'yes' if r['emits_spans'] else ' - ':5s} {r['log_lines']:>8d}  "
                  f"{'yes' if r['kernel_visible'] else ' - '}")
        print(f"  -> {n_span}/{len(rows)} emit request spans; "
              f"{len(rows)-n_span} are visible ONLY in metrics/logs/kernel")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(allrows, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}  ({len(allrows)} rows)")


if __name__ == "__main__":
    main()
