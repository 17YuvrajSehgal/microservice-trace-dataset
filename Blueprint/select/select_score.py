#!/usr/bin/env python3
"""Score blueprint SELECTION: did the router pick the blueprint whose family the fault belongs to?

Reads a dir of router result.json files, maps each committed fault_type to one of the five
blueprint families (synonym-aware - the agent uses its own vocabulary, e.g. "cpu_throttling"
for svc_cpu_cap), looks up the TRUE family from ground truth, and prints a confusion matrix +
per-family selection accuracy + the NORMAL (abstention) behaviour.

    python select_score.py <results_dir> --data-root <dir> [--data-root <dir> ...]

Selection is judged, not detection: picking svc_cpu_cap on a cpu-cap run is correct here even if
a downstream specialist would still have to localise it.
"""
import argparse
import glob
import json
import os
import sys

FAMILIES = ["svc_cpu_cap", "noisy_neighbor", "slow_db", "svc_net", "svc_mem_cap",
            # bare-metal / scheduling families (blueprints 8-11), routed by select_d
            "cpu_starvation", "syscall_stall", "irq_imbalance", "priority_inversion",
            "lock_contention", "normal"]

# order matters: specific/overlapping terms first (service_network has "net"; cpu competition is noisy)
def to_family(fault_type):
    s = (fault_type or "").lower()
    if not s or "normal" in s or "no fault" in s or "no injected" in s or s == "none":
        return "normal"
    # scheduling family first: "priority_inversion" contains "priority", "lock_contention"
    # contains "contention" (which the noisy_neighbor rule would also claim)
    if "inversion" in s:
        return "priority_inversion"
    if "lock" in s or "futex" in s or "deadlock" in s:
        return "lock_contention"
    if "starv" in s:
        return "cpu_starvation"
    if "stall" in s or "syscall" in s:
        return "syscall_stall"
    if "irq" in s or "softirq" in s or "interrupt" in s:
        return "irq_imbalance"
    if "mem" in s or "reclaim" in s or "oom" in s:
        return "svc_mem_cap"
    if "retrans" in s or "packet" in s or "service_network" in s or "svc_net" in s or "netem" in s \
            or ("net" in s and "network" in s):
        return "svc_net"
    if "db" in s or "dependency" in s or "database" in s or "sql" in s:
        return "slow_db"
    if "noisy" in s or "neighbor" in s or "competition" in s or "contention" in s:
        return "noisy_neighbor"
    if "cpu" in s or "throttl" in s or "quota" in s or "cap" in s:
        return "svc_cpu_cap"
    return "other"


def true_family(run_dir):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
    import score as S
    t = S.load_truth(run_dir)
    if t["present"] is False:
        return "normal"
    return t["family"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--data-root", action="append", default=[], help="where the run dirs live (repeatable)")
    a = ap.parse_args()

    rows = []
    for f in sorted(glob.glob(os.path.join(a.results_dir, "**", "result.json"), recursive=True)):
        r = json.load(open(f))
        rid = r["run_id"]
        rd = None
        for root in a.data_root:
            c = glob.glob(os.path.join(root, "**", rid), recursive=True)
            c = [x for x in c if os.path.isdir(x) and not x.rstrip("/\\").endswith("_metrics")]
            if c:
                rd = c[0]; break
        if rd is None:
            print("  (no run dir for %s)" % rid); continue
        picked = to_family((r.get("verdict") or {}).get("fault"))
        truth = true_family(rd)
        rows.append((rid, truth, picked))

    labels = FAMILIES + ["other"]
    # confusion matrix: true (row) x picked (col)
    conf = {t: {p: 0 for p in labels} for t in labels}
    for _, t, p in rows:
        conf.setdefault(t, {p: 0 for p in labels})
        conf[t][p] = conf[t].get(p, 0) + 1

    print("SELECTION CONFUSION MATRIX  (rows = true family, cols = router picked)\n")
    hdr = "true\\pick    " + " ".join("%-8s" % p[:8] for p in labels)
    print(hdr)
    correct = total = 0
    for t in labels:
        if sum(conf[t].values()) == 0:
            continue
        line = "%-12s" % t[:12] + " ".join("%-8d" % conf[t][p] for p in labels)
        print(line)
        correct += conf[t][t]
        total += sum(conf[t].values())
    print("\nper-family selection accuracy:")
    for t in labels:
        n = sum(conf[t].values())
        if n:
            print("  %-14s %d/%d" % (t, conf[t][t], n))
    print("\noverall: %d/%d = %.0f%% selected the correct blueprint" % (correct, total, 100 * correct / max(total, 1)))


if __name__ == "__main__":
    main()
