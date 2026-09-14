#!/usr/bin/env python3
"""Score the rule engine twice: counting every labelled run, and counting only runs whose
fault actually took. The difference is the size of the mistake we were making.

32 of 303 v2 runs carry `verification_status: unconfirmed` - the campaign's own metric checks
ran at collection time and did not see the fault. No analysis script read that, so those runs
were scored as if the fault were present. A blueprint that "missed" one of them did not miss
anything; there was nothing there.

Both numbers are printed because both are honest, and because the gap is the point.

    python3 blueprints/lib/score_with_verification.py --packs <dir>
"""
import argparse
import collections
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD  # noqa: E402
import verification as VF  # noqa: E402

OWNS = {"anomaly_cpu": "host-cpu-saturation", "noisy_neighbor": "cpu-contention-co-tenant",
        "svc_cpu_cap": "service-cpu-throttle", "anomaly_disk": "host-disk-saturation",
        "svc_mem_cap": "service-memory-cap", "slow_db": "datastore-wait",
        "anomaly_net": "network-path-degradation", "svc_net": "network-path-degradation"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--verification", default="")
    a = ap.parse_args()

    vindex = VF.load(a.verification or None)
    if not vindex:
        print("WARNING: no verification index - the two columns will be identical")

    runs = []
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not p.get("run_id"):
            continue
        fam = p.get("family_dir") or ""
        fam = fam[3:] if fam.startswith("tt_") else fam
        runs.append({"run": p["run_id"], "app": p.get("app"), "family": fam,
                     "selected": BD.decide(p).get("selected"),
                     "status": VF.status(p["run_id"], vindex),
                     "positive_ok": VF.usable_as_positive(p["run_id"], vindex, fam)})

    VF.report([r["run"] for r in runs], vindex)
    print()

    def score(only_verified):
        hit = miss = false = quiet = 0
        per = collections.defaultdict(lambda: [0, 0])
        for r in runs:
            want = OWNS.get(r["family"])
            if want:
                if only_verified and not r["positive_ok"]:
                    # Its fault did not take, so it is not a positive. It is still a real run
                    # in which nothing happened - so if a blueprint fires on it, that is a
                    # FALSE FIRE, not a hit. Dropping it from both columns would quietly
                    # improve the score by deleting the evidence.
                    if r["selected"]:
                        false += 1
                    else:
                        quiet += 1
                    continue
                per[(r["app"], r["family"])][1] += 1
                if r["selected"] == want:
                    hit += 1
                    per[(r["app"], r["family"])][0] += 1
                else:
                    miss += 1
            else:
                if r["selected"]:
                    false += 1
                else:
                    quiet += 1
        return hit, miss, false, quiet, per

    a_hit, a_miss, a_false, a_quiet, a_per = score(False)
    b_hit, b_miss, b_false, b_quiet, b_per = score(True)

    print("%-44s %-18s %s" % ("", "every labelled run", "only runs whose fault took"))
    print("-" * 92)
    print("%-44s %-18s %s"
          % ("runs a blueprint owns", a_hit + a_miss, b_hit + b_miss))
    print("%-44s %-18s %s"
          % ("  correct", "%d (%.0f%%)" % (a_hit, 100.0 * a_hit / max(1, a_hit + a_miss)),
             "%d (%.0f%%)" % (b_hit, 100.0 * b_hit / max(1, b_hit + b_miss))))
    print("%-44s %-18s %s" % ("  missed", a_miss, b_miss))
    print("%-44s %-18s %s"
          % ("runs that should produce no verdict", a_false + a_quiet,
             b_false + b_quiet))
    print("%-44s %-18s %s" % ("  false fires", a_false, b_false))
    print()
    print("--- per family: correct / scored ---")
    print("%-12s %-22s %-14s %s" % ("app", "family", "every run", "fault took"))
    for k in sorted(set(a_per) | set(b_per)):
        app, fam = k
        av = a_per.get(k, [0, 0])
        bv = b_per.get(k, [0, 0])
        flag = "   <-- " if av != bv else ""
        print("%-12s %-22s %-14s %s%s"
              % (app, fam, "%d/%d" % (av[0], av[1]), "%d/%d" % (bv[0], bv[1]), flag))

    dropped = [r for r in runs if OWNS.get(r["family"]) and not r["positive_ok"]]
    if dropped:
        print()
        print("--- runs no longer scored as positives (%d) ---" % len(dropped))
        c = collections.Counter((r["app"], r["family"], r["status"]) for r in dropped)
        for (app, fam, st), n in sorted(c.items()):
            print("  %-12s %-22s %-20s %d" % (app, fam, st, n))


if __name__ == "__main__":
    main()
