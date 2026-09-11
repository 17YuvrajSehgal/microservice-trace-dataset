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


def iops_per_irq(pack):
    """Disk arrivals per unit of interrupt rise.

    `anomaly_disk` and `svc_mem_cap` are the only pair these two rules confuse, and NO single
    signal separates them on both applications - the overlap is in opposite directions
    (arrivals separate them on Sock Shop, interrupt time on Train Ticket). Both faults raise
    both numbers; what differs is the mix. A disk flood is many requests for a modest
    interrupt rise; reclaim inside a cgroup is a large interrupt rise for few requests.
    """
    g = sig(pack, "blockio", "io_newcomer_iops_gained")
    x = sig(pack, "irq", "hardirq_x")
    if g is None or not x:
        return None
    return round(g / x, 1)


def num(v):
    """Ratios can be the string "from_zero" - a rate that was zero and is not any more. That is
    a fact, not a number, so it is excluded from cut-finding rather than coerced into one."""
    return v if isinstance(v, (int, float)) else None


def proc(pack, key):
    return num(((pack.get("process") or {}).get("signature") or {}).get(key))


def irq(pack, key):
    return num(((pack.get("irq") or {}).get("signature") or {}).get(key))


def util_ratio(pack):
    b, i = sig(pack, "oncpu", "host_util_baseline"), sig(pack, "oncpu", "host_util_incident")
    return round(i / b, 4) if (b and i is not None) else None


RULES = {
    "host-disk-saturation": ({"anomaly_disk"}, [
        ("iops_gained", lambda p: sig(p, "blockio", "io_newcomer_iops_gained"), ">=", 2000.0),
        ("total_iops_x", lambda p: sig(p, "blockio", "total_iops_x"), ">=", None),
        ("queue_depth_x", lambda p: sig(p, "blockio", "queue_depth_x"), ">=", None),
        ("hardirq_x", lambda p: sig(p, "irq", "hardirq_x"), ">=", None),
        ("iops_per_irq", iops_per_irq, ">=", None),
    ]),
    "service-memory-cap": ({"svc_mem_cap"}, [
        ("hardirq_x", lambda p: sig(p, "irq", "hardirq_x"), ">=", 2.5),
        ("iops_gained", lambda p: sig(p, "blockio", "io_newcomer_iops_gained"), "<=", 500.0),
        ("softirq_x", lambda p: sig(p, "irq", "softirq_x"), ">=", None),
        ("total_iops_x", lambda p: sig(p, "blockio", "total_iops_x"), ">=", None),
        ("iops_per_irq", iops_per_irq, "<=", None),
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

    # ---------------------------------------------------------------------------------------
    # THE 16 FAMILIES WITH NO BLUEPRINT. Everything below is a CANDIDATE TO TEST, not a claim.
    #
    # Each signal is here because the fault's own recipe describes a mechanism that should move
    # it, or because the signal is the same shape as one that already works. Neither is
    # evidence. The tool decides: a cut is reported only if it separates the family from every
    # other family, and a cut that works on one application is reported as FAILING.
    #
    # A family whose signals all overlap is a result - it says this fault has no kernel-trace
    # signature we can find - and belongs in the write-up rather than in a blueprint.
    # ---------------------------------------------------------------------------------------
    "fork-storm": ({"fork_storm"}, [
        # The recipe predicts this one is obvious. Measured on one run it is not: the host total
        # moves 1.77x because the machine already forks 134/s. The newcomer moved 27x.
        ("fork_newcomer_per_s", lambda p: proc(p, "fork_newcomer_per_s"), ">=", None),
        ("forks_per_s_x", lambda p: proc(p, "forks_per_s_x"), ">=", None),
    ]),
    "fd-exhaustion": ({"fd_exhaustion"}, [
        # The recipe says accept and socket return EMFILE while the process keeps running.
        ("emfile_per_s", lambda p: proc(p, "emfile_per_s_incident"), ">=", None),
        ("error_newcomer_per_s", lambda p: proc(p, "error_newcomer_per_s"), ">=", None),
    ]),
    "conn-pool-exhaustion": ({"conn_pool_exhaustion"}, [
        # Connections are refused or time out at connect().
        ("econnrefused_per_s", lambda p: proc(p, "econnrefused_per_s_incident"), ">=", None),
        ("etimedout_per_s", lambda p: proc(p, "etimedout_per_s_incident"), ">=", None),
        ("error_newcomer_per_s", lambda p: proc(p, "error_newcomer_per_s"), ">=", None),
    ]),
    "data-exfiltration": ({"data_exfiltration"}, [
        # The recipe already doubts itself: "the honest answer may be not from volume alone".
        ("tx_newcomer_bytes_per_s", lambda p: proc(p, "tx_newcomer_bytes_per_s"), ">=", None),
        ("tx_bytes_per_s_x", lambda p: proc(p, "tx_bytes_per_s_x"), ">=", None),
    ]),
    "dns-delay": ({"dns_delay"}, [
        # Slower lookups in a closed loop mean FEWER complete, so the rate may fall rather than
        # rise. Both directions are worth looking at, which is why the table prints the range.
        ("dns_packets_per_s_x", lambda p: proc(p, "dns_packets_per_s_x"), "<=", None),
    ]),
    "priority-inversion": ({"priority_inversion"}, [
        ("prio_non_default_pct", lambda p: proc(p, "prio_non_default_pct_incident"), ">=", None),
        ("n_distinct_prio", lambda p: proc(p, "n_distinct_prio_incident"), ">=", None),
        ("futex_p95_x", lambda p: irq(p, "futex_p95_x"), ">=", None),
    ]),
    "lock-contention": ({"lock_contention"}, [
        # LATENCY-CAUSES: key on the SHAPE, never the total. Idle thread pools park in futex for
        # ~300 ms each and drown any total; real contention is many SHORT waits.
        ("futex_short_waits_x", lambda p: irq(p, "futex_short_waits_x"), ">=", None),
        ("futex_p95_x", lambda p: irq(p, "futex_p95_x"), ">=", None),
        ("futex_wait_x", lambda p: irq(p, "futex_wait_x"), ">=", None),
    ]),
    "deadlock": ({"deadlock"}, [
        # Threads block in futex and never return, so the tail should stretch rather than the
        # count rise - the opposite shape to lock_contention, which is the interesting part.
        ("futex_p95_x", lambda p: irq(p, "futex_p95_x"), ">=", None),
        ("futex_wait_x", lambda p: irq(p, "futex_wait_x"), ">=", None),
        ("futex_short_waits_x", lambda p: irq(p, "futex_short_waits_x"), "<=", None),
    ]),
    "resource-abuse": ({"resource_abuse"}, [
        # A hidden CPU loop: the same shape as noisy_neighbor, which thief_cores already gets
        # 26/26. If it separates here too, the two faults may not be separable from each other,
        # and that would be the finding.
        ("thief_cores", lambda p: sig(p, "oncpu", "thief_cores_gained"), ">=", None),
        ("tx_newcomer_bytes_per_s", lambda p: proc(p, "tx_newcomer_bytes_per_s"), ">=", None),
    ]),
    "host-memory-pressure": ({"anomaly_mem"}, [
        # LATENCY-CAUSES cause 8 records this as working on ONE application only. Retested here
        # against every family rather than against its own control.
        ("hardirq_x", lambda p: irq(p, "hardirq_x"), ">=", None),
        ("iops_gained", lambda p: sig(p, "blockio", "io_newcomer_iops_gained"), ">=", None),
        ("total_iops_x", lambda p: sig(p, "blockio", "total_iops_x"), ">=", None),
    ]),
    # The five code defects share one metrics signature (DATASET-v2-INVENTORY). Whether the
    # kernel can tell them apart is the open question the ablation study exists to answer, so
    # they are tested as one family first: can we even see that SOMETHING is wrong?
    "code-defects": ({"code_event_loop_block", "code_lock_across_io", "code_n_plus_one",
                      "code_serial_awaits", "code_unbounded_cache"}, [
        ("n_slowed_2x", lambda p: sig(p, "endpoints", "n_slowed_2x"), ">=", None),
        ("socket_block_x", socket_max, ">=", None),
        ("futex_p95_x", lambda p: irq(p, "futex_p95_x"), ">=", None),
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


def band_cut(pos, neg):
    """A two-sided rule: does the positives' range exclude every negative?

    The one-sided cut misreports any rule whose family sits BETWEEN two others. The co-tenant
    rule is exactly that - `anomaly_cpu` steals more CPU than a co-tenant, not less - so its
    shipped `0.5 <= thief < 4.0` is a band and reporting it as "overlaps" says nothing.

    Edges are placed midway to the nearest negative, not on the positives' extremes, so a run
    slightly outside the observed range still lands inside.
    """
    if not pos or not neg:
        return None
    lo, hi = min(pos), max(pos)
    inside = [v for v in neg if lo <= v <= hi]
    below = max([v for v in neg if v < lo], default=None)
    above = min([v for v in neg if v > hi], default=None)
    return {
        "band": [round((below + lo) / 2, 4) if below is not None else None,
                 round((above + hi) / 2, 4) if above is not None else None],
        "pos_range": [lo, hi], "n_neg_inside": len(inside), "separates": not inside}


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

            res, bands = {}, {}
            for app in ("sockshop", "trainticket", "both"):
                if app == "both":
                    pos = vals[("sockshop", True)] + vals[("trainticket", True)]
                    neg = vals[("sockshop", False)] + vals[("trainticket", False)]
                else:
                    pos, neg = vals[(app, True)], vals[(app, False)]
                c = best_cut(pos, neg, direction)
                b = band_cut(pos, neg)
                res[app], bands[app] = c, b
                if c:
                    ok = "CLEAN" if c["separates"] else "overlaps"
                    print(f"      [{app:11s}] cut {c['rule']:>14s}  "
                          f"recall {c['recall'][0]}/{c['recall'][1]}  {ok}")
                if b and not (c and c["separates"]) and b["separates"]:
                    lo, hi = b["band"]
                    lo_s = "-inf" if lo is None else f"{lo:.4g}"
                    hi_s = "+inf" if hi is None else f"{hi:.4g}"
                    print(f"      [{app:11s}] BAND {lo_s} .. {hi_s}  "
                          f"holds all {len(pos)} positives, 0 negatives inside")
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
            sb, tb = bands.get("sockshop"), bands.get("trainticket")
            if sb and tb and sb["separates"] and tb["separates"] and not (
                    res.get("sockshop", {}) or {}).get("separates"):
                print("      => BAND TRANSFERS on both applications.")
            out[rule][label] = {"direction": direction, "current": current,
                                "cuts": res, "bands": bands}

    if a.out:
        json.dump(out, open(a.out, "w"), indent=2, default=str)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
