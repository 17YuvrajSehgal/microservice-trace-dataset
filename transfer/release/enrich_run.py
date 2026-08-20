#!/usr/bin/env python3
"""Make one extracted run SELF-CONTAINED, and drop a copy of its small files into the lite tree.

Adds to the run dir (nothing is ever removed):
  kernel_l2.jsonl        from the working set (derived after the archives were made)
  kernel_l1/l3           backfilled only if the archive lacks them
  metrics/               from the <run>_metrics sibling
  load.csv               from the <run>_load.csv sibling
  RUN-INFO.txt           human-readable summary of what this run is

Usage: enrich_run.py <run_dir> <working_set_app_root> <family> <lite_root>
"""
import json, os, shutil, sys

rd, ws_app, family, lite_root = sys.argv[1:5]
run = os.path.basename(rd.rstrip("/"))
ws_run = os.path.join(ws_app, family, run)
added = []

def take(src, dst_name):
    dst = os.path.join(rd, dst_name)
    if os.path.exists(dst) or not os.path.exists(src):
        return False
    (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
    added.append(dst_name)
    return True

take(os.path.join(ws_run, "kernel_l2.jsonl"), "kernel_l2.jsonl")
take(os.path.join(ws_run, "kernel_l1.parquet"), "kernel_l1.parquet")   # backfill only
take(os.path.join(ws_run, "kernel_l3.jsonl"), "kernel_l3.jsonl")
take(os.path.join(ws_app, run + "_metrics"), "metrics")
take(os.path.join(ws_app, run + "_load.csv"), "load.csv")

# ---- RUN-INFO.txt -------------------------------------------------------------------
gt = {}
p = os.path.join(rd, "ground_truth.json")
if os.path.exists(p):
    try: gt = json.load(open(p)).get("fault", {})
    except Exception: pass
vs = ""
p = os.path.join(rd, "verification.json")
if os.path.exists(p):
    try: vs = json.load(open(p)).get("verification_status", "")
    except Exception: pass

if gt:
    kind = "FAULT RUN"
    what = (f"  fault type      : {gt.get('name','?')}  (family {gt.get('family','?')})\n"
            f"  broken on       : {gt.get('target_service','?')}   scope={gt.get('scope','?')}\n"
            f"  how hard        : {gt.get('intensity','?')}\n"
            f"  settings        : {json.dumps(gt.get('parameters', {}))}\n"
            f"  fault window UTC: {gt.get('injection_start_utc','?')} .. {gt.get('injection_end_utc','?')}\n"
            f"  expected to show: {gt.get('expected_winning_modality','?')} data\n"
            f"  fault confirmed : {vs or 'n/a'}\n")
elif family == "normal":
    kind, what = "CONTROL RUN (no fault)", "  Nothing was broken. Use these to see what healthy looks like.\n"
elif family == "lttng_only":
    kind, what = "OVERHEAD RUN (no fault)", "  Used to measure what the tracing itself costs. Not a fault example.\n"
else:
    kind, what = "RUN", ""

have = lambda n: "yes" if os.path.exists(os.path.join(rd, n)) else "no "
info = f"""{run}
{'=' * len(run)}
{kind}

{what}
Timeline: 4 minutes total - 60s healthy, 120s fault, 60s recovery.
Compare against the first 60 seconds; raw numbers alone mean little.

What is in this folder
  ground_truth.json   {have('ground_truth.json')}   the answer (do not show this to a model under test)
  verification.json   {have('verification.json')}   machine check that the fault really fired
  verification.png    {have('verification.png')}   the same check as a picture - open this first
  metrics/            {have('metrics')}   Prometheus metrics for this run
  load.csv            {have('load.csv')}   per-request results from the load generator
  logs/               {have('logs')}   application logs, one file per container
  otlp/               {have('otlp')}   distributed traces (spans)
  kernel/             {have('kernel')}   RAW kernel recording, L0 (binary CTF, needs babeltrace2)
  ust/                {have('ust')}   spans copied into the kernel recording (clock bridge)
  kernel_l1.parquet   {have('kernel_l1.parquet')}   L1 - kernel numbers, per service per second
  kernel_l2.jsonl     {have('kernel_l2.jsonl')}   L2 - what each service was WAITING for
  kernel_l3.jsonl     {have('kernel_l3.jsonl')}   L3 - plain-English summaries
  meta/               {have('meta')}   clock anchors + container-to-process map

See UNDERSTANDING-DATASET.md at the top of the dataset for what each file means.
"""
open(os.path.join(rd, "RUN-INFO.txt"), "w").write(info)

# ---- lite copy (small files only) ---------------------------------------------------
ld = os.path.join(lite_root, run)
os.makedirs(ld, exist_ok=True)
for n in ("RUN-INFO.txt", "ground_truth.json", "verification.json", "verification.png",
          "kernel_l1.parquet", "kernel_l2.jsonl", "kernel_l3.jsonl", "load.csv"):
    s = os.path.join(rd, n)
    if os.path.exists(s): shutil.copy2(s, os.path.join(ld, n))
s = os.path.join(rd, "metrics")
if os.path.isdir(s) and not os.path.isdir(os.path.join(ld, "metrics")):
    shutil.copytree(s, os.path.join(ld, "metrics"))

print(f"  {run}: added [{', '.join(added) if added else 'nothing new'}]")
