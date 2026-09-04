#!/usr/bin/env python3
"""Add the interrupt-time and block-I/O measurements to each evidence pack.

WHY
---
The packs carry runqueue_delay, blocking_syscall, call_graph, oncpu, endpoints and netloss.
They do NOT carry the block layer or the interrupt layer. That is why `host-disk-saturation`
sits in blueprint_decide's VERDICTS table but is never actually evaluated - the data it needs
was never in the pack - and the new `service-memory-cap` blueprint would have the same
problem.

Both sweeps already ran over every run we have, so nothing needs re-measuring. This just
merges their results in, the same way add_oncpu_to_pack.py and add_netevidence_to_pack.py did
for earlier signals.

    python3 add_irqio_to_pack.py --packs <dir> --irq <report.json> --blockio <summary.json>
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys


def norm(run_id: str) -> str:
    """Strip the app prefix the sweeps add, so ids line up with the pack filenames.

    futex/irq report : "sockshop_anomaly_cpu_..." / "trainticket_tt_anomaly_cpu_..."
    pack filename    : "anomaly_cpu_..."          / "tt_anomaly_cpu_..."
    """
    return re.sub(r"^(sockshop|trainticket)_", "", run_id)


def load_irq(path):
    out = {}
    for r in json.load(open(path, encoding="utf-8"))["runs"]:
        s = r.get("summary") or {}
        h = s.get("hardirq_s_per_s") or {}
        if h.get("x") is None:
            continue
        out[norm(r["run"])] = {
            "hardirq_x": h.get("x"),
            "hardirq_s_per_s_baseline": h.get("baseline"),
            "hardirq_s_per_s_incident": h.get("incident"),
            "softirq_x": (s.get("softirq_s_per_s") or {}).get("x"),
            "futex_p95_x": (s.get("futex_p95_ms") or {}).get("x"),
            "futex_wait_x": (s.get("futex_wait_s_per_s") or {}).get("x"),
        }
    return out


def load_blockio(path):
    out = {}
    for r in json.load(open(path, encoding="utf-8"))["rows"]:
        out[norm(r["run_id"])] = {
            "io_newcomer": r.get("io_newcomer"),
            "io_newcomer_iops_gained": r.get("io_newcomer_iops_gained"),
            "total_iops_x": r.get("total_iops_x"),
            "worst_device_p95_x": r.get("worst_device_p95_x"),
            "queue_depth_baseline": r.get("queue_depth_baseline"),
            "queue_depth_incident": r.get("queue_depth_incident"),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True, help="dir of pack json files (one app)")
    ap.add_argument("--irq", required=True)
    ap.add_argument("--blockio", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    irq, blk = load_irq(a.irq), load_blockio(a.blockio)
    print(f"irq rows {len(irq)}, blockio rows {len(blk)}")

    files = sorted(glob.glob(os.path.join(a.packs, "*.json")))
    both = one = none = 0
    for f in files:
        rid = os.path.basename(f)[:-5]
        d = json.load(open(f, encoding="utf-8"))
        i, b = irq.get(rid), blk.get(rid)
        if i:
            d["irq"] = {"signature": i}
        if b:
            d["blockio"] = {"signature": b}
        if i and b:
            both += 1
        elif i or b:
            one += 1
        else:
            none += 1
            continue
        if not a.dry_run:
            # follow the symlink rather than replacing it: allpacks is 86 symlinks into the
            # real pack dirs, and writing through would turn them into ordinary files
            json.dump(d, open(os.path.realpath(f), "w", encoding="utf-8"), indent=2)

    print(f"{len(files)} packs: {both} got both signals, {one} got one, {none} got neither")
    if none:
        have = set(irq) | set(blk)
        missing = [os.path.basename(f)[:-5] for f in files
                   if os.path.basename(f)[:-5] not in have]
        print("  no measurement for:", missing[:6], "..." if len(missing) > 6 else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
