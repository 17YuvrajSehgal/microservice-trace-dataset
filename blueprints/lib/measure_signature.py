#!/usr/bin/env python3
"""Measure what a fault family ACTUALLY looks like in our data, before anything is claimed.

This runs first. A blueprint discriminator may only be written from this output — never
from prior knowledge about how a fault "should" present. Confidence is not evidence.

For every labelled run of one or more families it reports, per service:
  * kernel L2 wait shares      on_cpu / runnable_wait / disk_wait / off_cpu_io_wait
  * kernel L1 movement         scheduler, syscall latency, block, net (incident vs baseline)
  * container metrics          cpu, throttling, memory, net (incident vs baseline)
  * trace edge slowdown        which caller->callee edges inflate, and where they converge

Then it contrasts families: a signal is only DISCRIMINATIVE if it separates the target
family from the others. Anything that moves the same way everywhere is a symptom, not a
discriminator, and must not be written into a blueprint as one.

    python3 measure_signature.py --families noisy_neighbor,slow_db --out evidence/
    python3 measure_signature.py --run <run_dir> --out evidence/     # single run
"""
from __future__ import annotations
import argparse, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "agentic-rca"))


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def l2_shares(run_dir):
    """Per-service wait decomposition from kernel L2, if it has been derived."""
    p = os.path.join(run_dir, "kernel_l2.jsonl")
    if not os.path.exists(p):
        return {}, "kernel_l2.jsonl not present - derive it before claiming any wait-share signature"
    out = {}
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[r.get("service", "?")] = {
                "shares_pct": r.get("rule_out_pct", {}),
                "verdict_hint": r.get("verdict_hint"),
                "seconds": r.get("seconds", {}),
            }
    return out, None


def l1_movement(run_dir, baseline_s=60, incident_s=180):
    """Per-service L1 KPI change, incident window vs the healthy first minute."""
    try:
        import pandas as pd
    except ImportError:
        return {}, "pandas unavailable"
    p = os.path.join(run_dir, "kernel_l1.parquet")
    if not os.path.exists(p):
        return {}, "kernel_l1.parquet not present"
    df = pd.read_parquet(p)
    if df.empty or "window_start_s" not in df:
        return {}, "kernel_l1 empty"
    base = df[df.window_start_s < baseline_s]
    inc = df[(df.window_start_s >= baseline_s) & (df.window_start_s < incident_s)]
    kpis = [c for c in ("sys_lat_p95_ms", "sys_lat_p99_ms", "blk_lat_p95_ms", "sched_switch",
                        "sched_wakeup", "block_ops", "net_bytes", "sys_io", "sys_futex",
                        "sys_poll", "reclaim", "pagefault") if c in df.columns]
    out = {}
    for svc in sorted(set(df.service.dropna())):
        b, i = base[base.service == svc], inc[inc.service == svc]
        if b.empty or i.empty:
            continue
        row = {}
        for k in kpis:
            bv, iv = float(b[k].mean()), float(i[k].mean())
            row[k] = {"baseline": round(bv, 4), "incident": round(iv, 4),
                      "x": round(iv / bv, 2) if bv else None}
        out[svc] = row
    return out, None


def edge_slowdown(run_dir, app):
    """Caller->callee p95 slowdown, and which component the slow edges converge on."""
    try:
        from stratatrace import load_run
        from tools import RunTools
    except ImportError as e:
        return {}, f"tools unavailable: {e}"
    try:
        t = RunTools(load_run(run_dir), app=app)
        topo, _ = t.topology(None)
    except Exception as e:                                             # noqa: BLE001
        return {}, f"topology failed: {type(e).__name__}: {e}"
    edges = topo.get("edges", []) if isinstance(topo, dict) else []
    incoming = {}
    outgoing = {}
    for e in edges:
        s = e.get("slowdown_x")
        if s is None:
            continue
        incoming.setdefault(e.get("callee"), []).append(s)
        outgoing.setdefault(e.get("caller"), []).append(s)
    conv = []
    for callee, ins in incoming.items():
        outs = outgoing.get(callee, [])
        conv.append({"component": callee,
                     "max_incoming_slowdown_x": round(max(ins), 2),
                     "n_incoming_slow_edges": sum(1 for x in ins if x >= 2),
                     "max_outgoing_slowdown_x": round(max(outs), 2) if outs else None,
                     "emits_spans": bool(outs)})
    conv.sort(key=lambda c: -c["max_incoming_slowdown_x"])
    return {"edges": edges[:12], "convergence": conv[:8]}, None


def measure(run_dir, app, family, run_id):
    rec = {"run_id": run_id, "app": app, "family": family, "run_dir": run_dir, "gaps": []}
    gt = {}
    p = os.path.join(run_dir, "ground_truth.json")
    if os.path.exists(p):
        try:
            gt = json.load(open(p)).get("fault", {})
        except Exception:                                              # noqa: BLE001
            pass
    rec["target_service"] = gt.get("target_service", "")

    l2, err = l2_shares(run_dir)
    rec["l2_wait_shares"] = l2
    if err:
        rec["gaps"].append(err)

    l1, err = l1_movement(run_dir)
    rec["l1_movement"] = l1
    if err:
        rec["gaps"].append(err)

    topo, err = edge_slowdown(run_dir, app)
    rec["topology"] = topo
    if err:
        rec["gaps"].append(err)
    return rec


def contrast(records):
    """A signal only counts as discriminative if it separates its family from the rest."""
    fams = sorted({r["family"] for r in records})
    out = {"families": fams, "wait_share_by_family": {}, "note":
           "A share that behaves the same across families is a SYMPTOM, not a discriminator."}
    for fam in fams:
        rs = [r for r in records if r["family"] == fam]
        buckets = {"on_cpu": [], "runnable_wait": [], "disk_wait": [], "off_cpu_io_wait": []}
        hints = []
        for r in rs:
            tgt = r.get("target_service", "")
            for svc, v in (r.get("l2_wait_shares") or {}).items():
                # prefer the labelled culprit; otherwise take every service
                if tgt and tgt not in svc and svc not in tgt:
                    continue
                for k in buckets:
                    if k in v.get("shares_pct", {}):
                        buckets[k].append(v["shares_pct"][k])
                if v.get("verdict_hint"):
                    hints.append(v["verdict_hint"])
        out["wait_share_by_family"][fam] = {
            "n_runs": len(rs),
            "mean_pct": {k: _mean(v) for k, v in buckets.items()},
            "verdict_hints": sorted(set(hints)),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", default="", help="comma-separated fault families")
    ap.add_argument("--app", default="both", choices=["sockshop", "trainticket", "both"])
    ap.add_argument("--run", default="", help="measure a single run directory")
    ap.add_argument("--app-of-run", default="sockshop")
    ap.add_argument("--per-family", type=int, default=0, help="0 = all runs")
    ap.add_argument("--out", default="evidence")
    a = ap.parse_args()

    records = []
    if a.run:
        records.append(measure(a.run.rstrip("/"), a.app_of_run,
                               os.path.basename(os.path.dirname(a.run.rstrip("/"))),
                               os.path.basename(a.run.rstrip("/"))))
    else:
        import runs as R
        fams = [f for f in a.families.split(",") if f]
        apps = ["sockshop", "trainticket"] if a.app == "both" else [a.app]
        for app in apps:
            seen = {}
            for rec in R.iter_runs(app):
                if fams and rec.fault_family not in fams:
                    continue
                if a.per_family and seen.get(rec.fault_family, 0) >= a.per_family:
                    continue
                seen[rec.fault_family] = seen.get(rec.fault_family, 0) + 1
                print(f"  measuring {rec.run_id} ...", flush=True)
                records.append(measure(rec.dir, app, rec.fault_family, rec.run_id))

    if not records:
        sys.exit("no runs measured")

    os.makedirs(a.out, exist_ok=True)
    per_run = os.path.join(a.out, "measurements.json")
    json.dump(records, open(per_run, "w"), indent=2, default=str)

    summary = contrast(records)
    json.dump(summary, open(os.path.join(a.out, "contrast.json"), "w"), indent=2, default=str)

    print(f"\nmeasured {len(records)} run(s) -> {per_run}")
    gaps = {g for r in records for g in r["gaps"]}
    for g in sorted(gaps):
        print(f"  GAP: {g}")
    print("\nwait shares of the labelled culprit, by family:")
    for fam, v in summary["wait_share_by_family"].items():
        m = v["mean_pct"]
        print(f"  {fam:20s} n={v['n_runs']}  on_cpu={m['on_cpu']}  runnable={m['runnable_wait']}  "
              f"disk={m['disk_wait']}  ext_io={m['off_cpu_io_wait']}")
        if v["verdict_hints"]:
            print(f"  {'':20s} hints: {', '.join(v['verdict_hints'])}")
    print("\nA share that looks the same across families is NOT a discriminator.")


if __name__ == "__main__":
    sys.exit(main())
