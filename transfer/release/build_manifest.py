#!/usr/bin/env python3
"""Build manifest.csv + per-app READMEs from the finished lite tree."""
import csv, json, os, collections

DEST = "/scratch/yuvraj17/stratatrace-v1"
LITE = os.path.join(DEST, "_lite")

PLAIN = {
    "anomaly_cpu": "Host CPU overload", "anomaly_disk": "Host disk overload",
    "anomaly_mem": "Host memory exhaustion", "anomaly_net": "Host network degradation",
    "slow_db": "Slow database", "error_storm": "Error burst",
    "dependency_outage": "Frozen dependency", "queue_backlog": "Silent queue backlog",
    "noisy_neighbor": "Noisy neighbour container", "svc_cpu_cap": "Service CPU limit",
    "svc_mem_cap": "Service memory cap", "svc_net": "Single-service network fault",
    "normal": "No fault (control)", "lttng_only": "No fault (tracing-overhead run)",
}

rows = []
for app in sorted(os.listdir(LITE)):
    ad = os.path.join(LITE, app)
    if not os.path.isdir(ad): continue
    for fam in sorted(os.listdir(ad)):
        fd = os.path.join(ad, fam)
        if not os.path.isdir(fd): continue
        for run in sorted(os.listdir(fd)):
            rd = os.path.join(fd, run)
            if not os.path.isdir(rd): continue
            gt, vs = {}, ""
            p = os.path.join(rd, "ground_truth.json")
            if os.path.exists(p):
                try: gt = json.load(open(p)).get("fault", {})
                except Exception: pass
            p = os.path.join(rd, "verification.json")
            if os.path.exists(p):
                try: vs = json.load(open(p)).get("verification_status", "")
                except Exception: pass
            has = lambda n: int(os.path.exists(os.path.join(rd, n)))
            rows.append(dict(
                app=app, family=fam, fault_plain=PLAIN.get(fam, fam), run_id=run,
                run_type=("fault" if gt else "control" if fam == "normal" else "overhead"),
                target=gt.get("target_service", ""), scope=gt.get("scope", ""),
                intensity=gt.get("intensity", ""),
                fault_start_utc=gt.get("injection_start_utc", ""),
                fault_end_utc=gt.get("injection_end_utc", ""),
                expected_modality=gt.get("expected_winning_modality", ""),
                verification=vs,
                has_l1=has("kernel_l1.parquet"), has_l2=has("kernel_l2.jsonl"),
                has_l3=has("kernel_l3.jsonl"), has_metrics=int(os.path.isdir(os.path.join(rd, "metrics"))),
                has_load=has("load.csv"), has_verif_png=has("verification.png"),
            ))

out = os.path.join(DEST, "manifest.csv")
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(f"manifest.csv: {len(rows)} runs")

for app in sorted({r["app"] for r in rows}):
    rs = [r for r in rows if r["app"] == app]
    fams = collections.Counter(r["family"] for r in rs)
    lines = [f"# {app} runs", "",
             f"{len(rs)} runs: {sum(1 for r in rs if r['run_type']=='fault')} with a fault, "
             f"{sum(1 for r in rs if r['run_type']=='control')} healthy controls, "
             f"{sum(1 for r in rs if r['run_type']=='overhead')} tracing-overhead runs.", "",
             "One archive per fault type. Download only the ones you need.", "",
             "| archive | what was broken | runs | broken on |", "|---|---|---|---|"]
    for fam in sorted(fams):
        tg = sorted({r["target"] for r in rs if r["family"] == fam and r["target"]})
        lines.append(f"| `{fam}.tar.gz` | {PLAIN.get(fam, fam)} | {fams[fam]} | {', '.join(tg) or '-'} |")
    lines += ["", "Every run folder is self-contained. See RUN-INFO.txt inside each run,",
              "and UNDERSTANDING-DATASET.md at the top of the dataset.", ""]
    d = os.path.join(DEST, app); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "README.md"), "w").write("\n".join(lines))
    print(f"  {app}/README.md  ({len(rs)} runs, {len(fams)} archives)")
