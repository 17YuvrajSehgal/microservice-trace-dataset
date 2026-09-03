#!/usr/bin/env python3
"""Inventory the CURRENT scattered dataset: what exists, where, for every run."""
import csv, os, subprocess, sys

WS   = "/scratch/yuvraj17/stratatrace/data/agentic-runs"
PROJ = "/project/def-naser2/yuvraj17/microservice-trace-dataset"
APPS = ("sockshop", "trainticket")

def sz(p):
    if not os.path.exists(p): return 0
    if os.path.isfile(p): return os.path.getsize(p)
    t = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            try: t += os.path.getsize(os.path.join(r, f))
            except OSError: pass
    return t

rows = []
for app in APPS:
    root = os.path.join(WS, app)
    if not os.path.isdir(root): continue
    # sibling aux at app root
    sib = set(os.listdir(root))
    for fam in sorted(os.listdir(root)):
        famd = os.path.join(root, fam)
        if not os.path.isdir(famd) or fam.endswith("_metrics"): continue
        for run in sorted(os.listdir(famd)):
            rd = os.path.join(famd, run)
            if not os.path.isdir(rd): continue
            rows.append(dict(
                app=app, family=fam, run_id=run,
                ground_truth=int(os.path.exists(f"{rd}/ground_truth.json")),
                verification=int(os.path.exists(f"{rd}/verification.json")),
                verif_png=int(os.path.exists(f"{rd}/verification.png")),
                l1=int(os.path.exists(f"{rd}/kernel_l1.parquet")),
                l2=int(os.path.exists(f"{rd}/kernel_l2.jsonl")),
                l3=int(os.path.exists(f"{rd}/kernel_l3.jsonl")),
                logs=int(os.path.isdir(f"{rd}/logs")),
                otlp=int(os.path.isdir(f"{rd}/otlp")),
                meta=int(os.path.isdir(f"{rd}/meta")),
                kernel_raw=int(os.path.isdir(f"{rd}/kernel")),
                ust=int(os.path.isdir(f"{rd}/ust")),
                metrics_sibling=int(f"{run}_metrics" in sib),
                load_sibling=int(f"{run}_load.csv" in sib),
                run_MB=round(sz(rd)/1e6, 1),
                metrics_MB=round(sz(os.path.join(root, run+"_metrics"))/1e6, 1),
            ))

out = "/scratch/yuvraj17/stratatrace/results/reorg/inventory.csv"
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

print(f"runs: {len(rows)}  -> {out}\n")
for app in APPS:
    rs = [r for r in rows if r["app"] == app]
    if not rs: continue
    print(f"--- {app}: {len(rs)} runs")
    for k in ("ground_truth","verification","verif_png","l1","l2","l3","logs","otlp","meta",
              "kernel_raw","ust","metrics_sibling","load_sibling"):
        n = sum(r[k] for r in rs)
        flag = "" if n == len(rs) else f"   <-- MISSING on {len(rs)-n}"
        print(f"    {k:16s} {n:3d}/{len(rs)}{flag}")
    print(f"    total run bytes: {sum(r['run_MB'] for r in rs)/1000:.1f} GB")
    print(f"    total metrics  : {sum(r['metrics_MB'] for r in rs)/1000:.1f} GB")
