#!/usr/bin/env python3
"""Read new thresholds off the v2 packs instead of guessing them.

For every signal a rule decides on, this prints the measured distribution per family, per
application, and then asks one question: is there a cut that separates the family this rule
owns from every other family, on BOTH applications?

    the cut is placed against the OTHER families' extreme, not tuned to maximise recall.
    a cut that only works on one application is REPORTED AS FAILING, not averaged.

That second rule is the one that matters. `LATENCY-CAUSES.md` ends on it: a discriminator does
not enter a blueprint until it has been checked on both applications, because one application
cannot tell you whether you found a property of the fault or a property of the deployment. The
whole-library test measured 71% on Sock Shop against 29% on Train Ticket precisely because every
shipped threshold was read off Sock Shop alone.

Runs whose fault the campaign could not confirm are EXCLUDED from the positive side by default:
a threshold fitted to make a fault fire that never happened is worse than no threshold.

    python3 derive_v2_thresholds.py --packs <dir> --tasks <file> [--v2 <root>] [--out json]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import sys

V2_DEFAULT = "/scratch/yuvraj17/stratatrace/data/stratatrace-v2"

# rule -> (owning families, [(label, extractor, direction, current threshold)])
# direction ">=" means the fault makes the number BIGGER.
def sig(pack, section, key):
    return ((pack.get(section) or {}).get("signature") or {}).get(key)


def rq_max(pack):
    rows = (pack.get("runqueue_delay") or {}).get("top_by_inflation") or []
    xs = [r.get("p95_x") for r in rows if isinstance(r.get("p95_x"), (int, float))]
    return max(xs) if xs else None


def socket_max(pack):
    """Largest inflation among socket-waiting syscalls, mirroring blueprint_decide._blk."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import blueprint_decide as BD
    rows = (pack.get("blocking_syscall") or {}).get("top_by_inflation") or []
    hits = [r["p95_x"] for r in rows
            if r.get("p95_x")
            and r["comm_syscall"].split("|")[-1] in BD.SOCKET_CALLS
            and not BD.is_infra(r["comm_syscall"].split("|")[0])]
    return max(hits) if hits else None


def util_ratio(pack):
    b, i = sig(pack, "oncpu", "host_util_baseline"), sig(pack, "oncpu", "host_util_incident")
    return round(i / b, 4) if (b and i is not None) else None


RULES = {
    "host-disk-saturation": ({"anomaly_disk"}, [
        ("iops_gained", lambda p: sig(p, "blockio", "io_newcomer_iops_gained"), ">=", 2000.0),
        ("total_iops_x", lambda p: sig(p, "blockio", "total_iops_x"), ">=", None),
        ("queue_depth_x", lambda p: sig(p, "blockio", "queue_depth_x"), ">=", None),
        ("hardirq_x", lambda p: sig(p, "irq", "hardirq_x"), ">=", None),
    ]),
    "service-memory-cap": ({"svc_mem_cap"}, [
        ("hardirq_x", lambda p: sig(p, "irq", "hardirq_x"), ">=", 2.5),
        ("iops_gained", lambda p: sig(p, "blockio", "io_newcomer_iops_gained"), "<=", 500.0),
        ("softirq_x", lambda p: sig(p, "irq", "softirq_x"), ">=", None),
        ("total_iops_x", lambda p: sig(p, "blockio", "total_iops_x"), ">=", None),
    ]),
    "service-cpu-throttle": ({"svc_cpu_cap"}, [
        ("util_ratio", util_ratio, "<=", 0.80),
        ("loser_cores", lambda p: sig(p, "oncpu", "biggest_loser_cores"), "<=", -0.30),
        ("rq_max", rq_max, ">=", 5.0),
        ("thief_cores", lambda p: sig(p, "oncpu", "thief_cores_gained"), "<=", 0.50),
    ]),
    "datastore-wait": ({"slow_db"}, [
        ("socket_block_x", socket_max, ">=", 5.0),
        ("worst_endpoint_x", lambda p: sig(p, "endpoints", "worst_endpoint_x"), ">=", 18.0),
        ("worst_retrans_pct", lambda p: sig(p, "netloss", "worst_retrans_pct"), "<=", 12.0),
    ]),
    "cpu-contention-co-tenant": ({"noisy_neighbor"}, [
        ("thief_cores", lambda p: sig(p, "oncpu", "thief_cores_gained"), ">=", 0.50),
        ("util_ratio", util_ratio, ">=", None),
        ("util_incident", lambda p: sig(p, "oncpu", "host_util_incident"), ">=", 0.55),
    ]),
}


def load_tasks(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) >= 3:
            out[p[2]] = (p[0], p[1])
    return out


def confirmed(v2, app, fam, run):
    try:
        p = os.path.join(v2, app, fam, run, "verification.json")
        return json.load(open(p)).get("verification_status") == "confirmed"
    except Exception:                                                  # noqa: BLE001
        return False


def best_cut(pos, neg, direction):
    """Place the cut against the NEGATIVES' extreme, then report the recall it buys.

    Deliberately not the cut that maximises recall: that fits the positives and is how a
    threshold ends up describing one deployment. Placing it against the negatives makes the
    false-fire rate zero by construction, and lets recall be the honest consequence.
    """
    if not pos or not neg:
        return None
    if direction == ">=":
        cut = max(neg)
        hits = sum(1 for v in pos if v > cut)
        return {"cut": cut, "rule": f"> {cut:.4g}", "recall": [hits, len(pos)],
                "pos_range": [min(pos), max(pos)], "neg_range": [min(neg), max(neg)],
                "separates": hits == len(pos)}
    cut = min(neg)
    hits = sum(1 for v in pos if v < cut)
    return {"cut": cut, "rule": f"< {cut:.4g}", "recall": [hits, len(pos)],
            "pos_range": [min(pos), max(pos)], "neg_range": [min(neg), max(neg)],
            "separates": hits == len(pos)}


def fmt(vals):
    if not vals:
        return "        (none)"
    return (f"n={len(vals):2d} min={min(vals):10.4g} med={statistics.median(vals):10.4g} "
            f"max={max(vals):10.4g}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--v2", default=V2_DEFAULT)
    ap.add_argument("--out", default="")
    ap.add_argument("--include-unconfirmed", action="store_true",
                    help="keep positives whose fault the campaign could not confirm")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    packs = {}
    for run, (app, fam) in truth.items():
        p = os.path.join(a.packs, f"{run}.json")
        if os.path.exists(p):
            packs[run] = (app, fam, json.load(open(p)))

    print("=" * 78)
    print(f" THRESHOLDS READ OFF v2  -  {len(packs)} packs")
    print(" cuts are placed against the other families' extreme, never fitted to the positives")
    print("=" * 78)

    out = {}
    for rule, (owns, signals) in RULES.items():
        print(f"\n{'=' * 78}\n {rule}   (owns {', '.join(sorted(owns))})\n{'=' * 78}")
        out[rule] = {}
        for label, get, direction, current in signals:
            vals = collections.defaultdict(list)      # (app, is_positive) -> [v]
            per_fam = collections.defaultdict(list)   # (app, fam) -> [v]
            for run, (app, fam, pk) in packs.items():
                v = get(pk)
                if v is None:
                    continue
                is_pos = fam in owns
                if is_pos and not a.include_unconfirmed and not confirmed(a.v2, app, fam, run):
                    continue                          # never fit to a fault that did not land
                vals[(app, is_pos)].append(v)
                per_fam[(app, fam)].append(v)

            print(f"\n  {label}   (currently {direction} {current})")
            for app in ("sockshop", "trainticket"):
                for fam in sorted({f for (ap_, f) in per_fam if ap_ == app}):
                    mark = " <-- OWNS" if fam in owns else ""
                    print(f"    {app:12s} {fam:16s} {fmt(per_fam[(app, fam)])}{mark}")

            res = {}
            for app in ("sockshop", "trainticket", "both"):
                if app == "both":
                    pos = vals[("sockshop", True)] + vals[("trainticket", True)]
                    neg = vals[("sockshop", False)] + vals[("trainticket", False)]
                else:
                    pos, neg = vals[(app, True)], vals[(app, False)]
                c = best_cut(pos, neg, direction)
                res[app] = c
                if c:
                    ok = "CLEAN" if c["separates"] else "overlaps"
                    print(f"      [{app:11s}] cut {c['rule']:>14s}  "
                          f"recall {c['recall'][0]}/{c['recall'][1]}  {ok}")
            # A cut that works on one application and not the other is the failure mode this
            # whole exercise exists to catch, so name it rather than reporting an average.
            s, t = res.get("sockshop"), res.get("trainticket")
            if s and t:
                if s["separates"] and t["separates"]:
                    print(f"      => TRANSFERS. safe cut = "
                          f"{max(s['cut'], t['cut']) if direction == '>=' else min(s['cut'], t['cut']):.4g}")
                elif s["separates"] or t["separates"]:
                    who = "Sock Shop" if s["separates"] else "Train Ticket"
                    print(f"      => ONE APP ONLY ({who}). Do not ship this as a single cut.")
                else:
                    print("      => separates on neither application.")
            out[rule][label] = {"direction": direction, "current": current, "cuts": res}

    if a.out:
        json.dump(out, open(a.out, "w"), indent=2, default=str)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
