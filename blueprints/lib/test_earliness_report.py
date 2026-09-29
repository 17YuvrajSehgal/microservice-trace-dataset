"""Prove the whole earliness path works, from a run's score.json to the printed report.

No cluster: synthesise a small results tree with the field shapes q2_run_one actually writes,
then generate the report and check the numbers land where a reader would look. The point is to
catch a break between scoring and reporting BEFORE the campaign, not after.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

LIB = "C:/workplace/microservice-trace-dataset/blueprints/lib"
sys.path.insert(0, LIB)

root = tempfile.mkdtemp(prefix="early_")
OUT = os.path.join(root, "report.md")
RES = os.path.join(root, "res")

# Two problems, deliberately different: one notices instantly, one notices a minute late. If the
# report cannot tell them apart, the metric is not doing its job.
SPEC = [("svc_net", "carts", 0.0, 1.0),
        ("slow_db", "catalogue-db", 62.0, 0.48)]

for prob, target, onset, iou in SPEC:
    for rep in range(1, 6):
        d = os.path.join(RES, prob, "%s_aggressive_steady_r1" % prob, "hint", "given",
                         "rep%d" % rep)
        os.makedirs(d, exist_ok=True)
        delay = max(0.0, onset)
        early = max(0.0, min(1.0, 1.0 - delay / 120.0))
        json.dump({
            "problem": prob, "run_id": "%s_aggressive_steady_r1" % prob,
            "arm": "given", "ask": "hint", "repeat": rep,
            "true_service": target, "where": "named",
            "window_verdict": "hit" if iou >= 0.5 else "partial",
            "window_iou": iou, "window_recall": iou, "window_precision": iou,
            "window_claimed": "10:00:00 - 10:02:00", "window_true": "10:00:00 - 10:02:00",
            "onset_error_s": onset, "detect_delay_s": delay,
            "earliness": round(early, 3), "earliness_gated": round(early * iou, 3),
            "what_score": 0.8, "fault_ok": True, "calls": 20, "seconds": 200, "tokens": 500000,
        }, io.open(os.path.join(d, "score.json"), "w", encoding="utf-8"), indent=1)

# one abstention, which must NOT drag the average down
d = os.path.join(RES, "svc_net", "svc_net_aggressive_steady_r1", "hint", "none", "rep1")
os.makedirs(d, exist_ok=True)
json.dump({"problem": "svc_net", "run_id": "svc_net_aggressive_steady_r1",
           "arm": "none", "ask": "hint", "repeat": 1, "true_service": "carts",
           "where": "named", "window_verdict": "abstained", "window_iou": None,
           "window_claimed": "unknown", "window_true": "10:00:00 - 10:02:00",
           "onset_error_s": None, "detect_delay_s": None,
           "earliness": None, "earliness_gated": None,
           "what_score": 0.5, "fault_ok": False, "calls": 5, "seconds": 60, "tokens": 100000},
          io.open(os.path.join(d, "score.json"), "w", encoding="utf-8"), indent=1)

r = subprocess.run([sys.executable, os.path.join(LIB, "q2_onefile.py"),
                    "--full", RES, "--app-name", "Test", "--out", OUT],
                   capture_output=True, text=True)
print("generator rc=%d" % r.returncode)
if r.returncode:
    print(r.stdout[-1500:])
    print(r.stderr[-1500:])
    sys.exit(1)

t = io.open(OUT, encoding="utf-8").read()
checks = [
    ("table has a `noticed` column", "| noticed |" in t),
    ("fast problem shows +0s", "+0s" in t),
    ("slow problem shows +62s", "+62s" in t),
    ("the earliness section is present", "### How early it noticed" in t),
    ("the gate is explained", "trivially gamed" in t),
    ("abstention policy is stated", "An abstention scores nothing, not zero" in t),
    ("no crash on the None row", "not scored" not in t.split("### How early")[0]),
]
print()
for name, ok in checks:
    print("  %-40s %s" % (name, "PASS" if ok else "FAIL"))
print()
for ln in t.splitlines():
    if "noticed" in ln or ln.startswith("| svc_net") or ln.startswith("| slow_db"):
        print("  %s" % ln)
shutil.rmtree(root, ignore_errors=True)
print()
print("FAILURES: %d" % sum(1 for _n, ok in checks if not ok))
