"""For every fault family with no blueprint, is there a signal that separates it?

Answers one question per family: could we write a blueprint for this, and on what.

The rules are the same ones every threshold in this project follows:
  - the cut is placed against the OTHER families' extreme, never fitted to the positives
  - every other family is a negative, including the healthy control
  - a cut that works on one application and fails on the other is reported as FAILING,
    because one deployment cannot tell you whether you found a property of the fault or a
    property of the machine

    python3 blueprints/lib/sweep_uncovered.py --packs <dir>
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

COVERED = {"anomaly_cpu", "noisy_neighbor", "svc_cpu_cap", "anomaly_disk", "svc_mem_cap",
           "slow_db", "anomaly_net", "svc_net", "fork_storm", "data_exfiltration",
           "fd_exhaustion"}
CONTROL = "normal"


def s_(p, sec):
    return ((p.get(sec) or {}).get("signature") or {})


def _div(a, b):
    return (a / b) if (a is not None and b) else None


def signals(p):
    cpu, rq, blk, net, io_ = BD._cpu(p), BD._rq(p), BD._blk(p), BD._net(p), BD._io(p)
    pr, irq, bio, ep = s_(p, "process"), s_(p, "irq"), s_(p, "blockio"), s_(p, "endpoints")
    on = s_(p, "oncpu")
    out = {
        "host_util_incident": cpu["util_incident"],
        "util_ratio": cpu["util_ratio"],
        "thief_share": cpu["thief_share"],
        "loser_share": cpu["loser_share"],
        "n_frozen_comms": on.get("n_frozen_comms"),
        "frozen_cores_lost": on.get("frozen_cores_lost"),
        "runqueue_max_x": rq["max"],
        "runqueue_n_inflated": rq["n_inflated"],
        "socket_block_x": blk["max_socket_x"] or None,
        "any_block_x": blk["max_any_x"] or None,
        "worst_retrans_pct": net["worst_retrans_pct"],
        "worst_drop_pct": net["worst_drop_pct"],
        "n_impaired_ifaces": net["n_impaired_ifaces"],
        "worst_endpoint_x": net["worst_endpoint_x"],
        "n_endpoints_slowed": net["n_endpoints_slowed"],
        "worst_unanswered": ep.get("worst_unanswered_ratio"),
        "worst_response_ratio": ep.get("worst_response_ratio"),
        "n_hung_endpoints": ep.get("n_hung"),
        "n_endpoints_gone": ep.get("n_gone"),
        "median_tail_ratio": ep.get("median_tail_ratio_of_slowed"),
        "iops_per_irq": io_["iops_per_irq"],
        "hardirq_x": io_["hardirq_x"],
        "softirq_x": irq.get("softirq_x"),
        "futex_p95_x": irq.get("futex_p95_x"),
        "futex_wait_x": irq.get("futex_wait_x"),
        "futex_short_waits_x": irq.get("futex_short_waits_x"),
        "total_iops_x": bio.get("total_iops_x"),
        "queue_depth_x": bio.get("queue_depth_x"),
        "device_p95_x": bio.get("worst_device_p95_x"),
    }
    for k in ("forks_per_s_x", "syscall_errors_per_s_x", "emfile_per_s_incident",
              "econnrefused_per_s_x", "etimedout_per_s_x", "tx_bytes_per_s_x",
              "top_tx_bytes_per_s_x", "dns_packets_per_s_x", "prio_non_default_pct_incident",
              "n_distinct_prio_incident", "fork_newcomer_per_s", "tx_newcomer_bytes_per_s",
              "error_newcomer_per_s"):
        out[k] = pr.get(k)
    # dimensionless variants of the rates, since a rate ties a threshold to this machine
    out["fork_newcomer_share"] = _div(pr.get("fork_newcomer_per_s"),
                                      pr.get("forks_per_s_baseline"))
    out["tx_newcomer_share"] = _div(pr.get("tx_newcomer_bytes_per_s"),
                                    pr.get("tx_bytes_per_s_incident"))
    out["emfile_error_share"] = _div(pr.get("emfile_per_s_incident"),
                                     pr.get("syscall_errors_per_s_incident"))
    # Some pack fields carry a name or a flag rather than a number. Comparing those would
    # silently sort strings, so drop anything that is not numeric rather than coerce it.
    return {k: float(v) for k, v in out.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def try_separate(pos, neg):
    """Best one-sided cut, or a band. Returns (kind, recall, n_pos, margin, text) or None."""
    if not pos or not neg:
        return None
    best = None
    hi_n, lo_n = max(neg), min(neg)
    above = [v for v in pos if v > hi_n]
    if above:
        margin = (min(above) / hi_n) if hi_n > 0 else float("inf")
        best = ("above", len(above), len(pos), margin, "> %.4g" % hi_n)
    below = [v for v in pos if v < lo_n]
    if below and (best is None or len(below) > best[1]):
        margin = (lo_n / max(below)) if max(below) > 0 else float("inf")
        best = ("below", len(below), len(pos), margin, "< %.4g" % lo_n)
    if best is None or best[1] < len(pos):
        lo_p, hi_p = min(pos), max(pos)
        inside = [v for v in neg if lo_p <= v <= hi_p]
        if not inside:
            best = ("band", len(pos), len(pos), None, "%.4g .. %.4g" % (lo_p, hi_p))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows = []
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not p.get("run_id"):
            continue
        fam = p.get("family_dir") or ""
        fam = fam[3:] if fam.startswith("tt_") else fam
        rows.append((fam, p.get("app"), signals(p)))

    fams = sorted(set(r[0] for r in rows))
    uncovered = [f for f in fams if f not in COVERED and f != CONTROL]
    keys = sorted(rows[0][2])
    print("%d runs, %d families, %d with no blueprint, %d signals tried"
          % (len(rows), len(fams), len(uncovered), len(keys)))
    print()

    report = {}
    for fam in uncovered:
        apps = sorted(set(r[1] for r in rows if r[0] == fam))
        found = []
        for k in keys:
            # must hold with EVERY other family as a negative, on every application the
            # fault was collected on
            per_app = []
            for app in apps:
                pos = [r[2][k] for r in rows if r[0] == fam and r[1] == app
                       and r[2].get(k) is not None]
                neg = [r[2][k] for r in rows if r[0] != fam and r[1] == app
                       and r[2].get(k) is not None]
                per_app.append(try_separate(pos, neg))
            if not all(per_app) or any(x[1] < x[2] for x in per_app):
                continue
            # and a single cut must hold across both, not one per application
            pos = [r[2][k] for r in rows if r[0] == fam and r[2].get(k) is not None]
            neg = [r[2][k] for r in rows if r[0] != fam and r[2].get(k) is not None]
            joint = try_separate(pos, neg)
            both = bool(joint and joint[1] == joint[2])
            found.append((k, per_app[0][0], joint, both, len(apps)))
        found.sort(key=lambda t: (not t[3], -(t[2][3] or 0) if t[2] and t[2][3] else 0))
        report[fam] = found
        n_runs = sum(1 for r in rows if r[0] == fam)
        if not found:
            print("  %-24s %2d runs / %d app   NO SIGNAL SEPARATES IT" % (fam, n_runs, len(apps)))
        else:
            shared = [x for x in found if x[3]]
            tag = ("%d signal(s) with ONE cut for both apps" % len(shared) if shared
                   else "%d signal(s), but only per-application" % len(found))
            print("  %-24s %2d runs / %d app   %s" % (fam, n_runs, len(apps), tag))
            for k, kind, joint, both, _ in found[:4]:
                m = ("margin %.2fx" % joint[3]) if (joint and joint[3]) else "band"
                print("        %-28s %-6s %-22s %s%s"
                      % (k, kind, joint[4] if joint else "-", m,
                         "" if both else "   (per-app only)"))
        print()

    if a.out:
        io.open(a.out, "w", encoding="utf-8", newline=chr(10)).write(
            json.dumps({f: [[k, kind, j, b] for k, kind, j, b, _ in v]
                        for f, v in report.items()}, indent=1) + chr(10))
        print("wrote " + a.out)


if __name__ == "__main__":
    main()
