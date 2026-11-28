#!/usr/bin/env python3
# verify_v4.py - did the fault change the program's own stats? (the v4 counterpart of the
# Prometheus verification of v2 and v3)
#
#   verify_v4.py <run_dir> <kpi> <up|down> <factor>
#
# Each v4 program prints one line per second with key=value pairs. The KPI's median over the
# last 40 s before the injection is compared with its median from 20 s after the injection to the
# end of the fault window. A fault run is "confirmed" when the KPI moved by FACTOR in the expected
# direction; a healthy run is "quiet" when it did not. Anything else is "unconfirmed" or "moved".
import datetime
import json
import re
import statistics
import sys

run, kpi, direction, factor = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
gt = json.load(open(f"{run}/ground_truth.json"))["fault"]
a = datetime.datetime.strptime(gt["injection_start_utc"], "%Y-%m-%dT%H:%M:%SZ")
b = datetime.datetime.strptime(gt["injection_end_utc"], "%Y-%m-%dT%H:%M:%SZ")
before, during = [], []
for line in open(f"{run}/logs/program.log", errors="replace"):
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S* .*\b" + re.escape(kpi) + r"=([-0-9.]+)", line)
    if not m:
        continue
    t = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    v = float(m.group(2))
    if -40 <= (t - a).total_seconds() < 0:
        before.append(v)
    elif 20 <= (t - a).total_seconds() and t < b:
        during.append(v)
res = {"kpi": kpi, "direction": direction, "factor": factor, "mode": gt["mode"], "n_before": len(before), "n_during": len(during)}
if len(before) < 10 or len(during) < 10:
    res.update(verdict="no_data", note="too few stats lines: did the program stop printing?")
else:
    mb, md = statistics.median(before), statistics.median(during)
    moved = (md >= factor * max(mb, 1e-9)) if direction == "up" else (md <= max(mb, 1e-9) / factor)
    res.update(before_median=mb, during_median=md)
    res["verdict"] = ("confirmed" if moved else "unconfirmed") if gt["mode"] == "fault" else ("moved" if moved else "quiet")
print(json.dumps(res, indent=2))
