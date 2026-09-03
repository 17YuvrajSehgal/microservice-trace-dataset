#!/usr/bin/env python3
"""Which of the futex/irq signals survive the second application?

A signal measured on one deployment is a property of that deployment until it is checked on
another. Sock Shop: 12 CPUs, ~16 services, idles at 48%. Train Ticket: 16 CPUs, 40+ services,
idles at 82%. If a signal only works on one, it is not a finding.
"""
import json
from collections import defaultdict

SS = json.load(open("/scratch/yuvraj17/stratatrace/results/futexirq/report.json"))
TT = json.load(open("/scratch/yuvraj17/stratatrace/results/futexirq_trainticket/report.json"))


def per_run(rep, key):
    out = defaultdict(list)
    for r in rep["runs"]:
        v = r["summary"].get(key, {})
        if isinstance(v.get("x"), (int, float)):
            out[r["family"]].append(round(v["x"], 2))
    return {f: sorted(v) for f, v in out.items()}


for key, label in [("hardirq_s_per_s", "hardirq s/s"),
                   ("futex_wait_s_per_s", "futex wait s/s"),
                   ("futex_p95_ms", "futex p95 ms")]:
    s, t = per_run(SS, key), per_run(TT, key)
    print(f"\n{'='*78}\n{label}   (per-run ratios, incident vs baseline)\n{'='*78}")
    print(f"  {'family':20s} {'Sock Shop':>26s}   {'Train Ticket':>26s}")
    for fam in sorted(set(s) | set(t)):
        sv = s.get(fam, [])
        tv = t.get(fam, [])
        ss = f"{min(sv):.2f}-{max(sv):.2f} (n={len(sv)})" if sv else "-"
        ts = f"{min(tv):.2f}-{max(tv):.2f} (n={len(tv)})" if tv else "-"
        mark = ""
        if sv and tv:
            hi_s, hi_t = min(sv) >= 2.0, min(tv) >= 2.0
            if hi_s and hi_t:
                mark = "  BOTH"
            elif hi_s != hi_t:
                mark = "  ONLY ONE APP"
        print(f"  {fam:20s} {ss:>26s}   {ts:>26s}{mark}")

print(f"\n{'='*78}\nverdict on the hardirq separator\n{'='*78}")
s, t = per_run(SS, "hardirq_s_per_s"), per_run(TT, "hardirq_s_per_s")
for fam in ("anomaly_disk", "svc_mem_cap", "anomaly_mem"):
    sv, tv = s.get(fam, []), t.get(fam, [])
    others_s = [x for f, v in s.items() if f != fam and f != "anomaly_disk" for x in v]
    others_t = [x for f, v in t.items() if f != fam and f != "anomaly_disk" for x in v]
    if fam == "anomaly_disk":
        others_s = [x for f, v in s.items() if f != fam for x in v]
        others_t = [x for f, v in t.items() if f != fam for x in v]
    ok_s = bool(sv) and bool(others_s) and min(sv) > max(others_s)
    ok_t = bool(tv) and bool(others_t) and min(tv) > max(others_t)
    print(f"  {fam:16s} sock shop separated: {str(ok_s):5s}   "
          f"train ticket separated: {str(ok_t):5s}")
    if sv:
        print(f"                   SS {min(sv):.2f}-{max(sv):.2f} vs rest max {max(others_s):.2f}")
    if tv:
        print(f"                   TT {min(tv):.2f}-{max(tv):.2f} vs rest max {max(others_t):.2f}")
