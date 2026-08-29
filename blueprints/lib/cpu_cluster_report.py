#!/usr/bin/env python3
"""Read the CPU-cluster measurements and show whether the families actually separate.

Four families all raise runqueue delay, so that signal cannot be the discriminator
(finding F2). This asks what else the scheduler stream offers:

    thief          did some process gain CPU it was not previously using?
    host_util      did the host run out of headroom?
    biggest_loser  did some process LOSE CPU?

Expected — but expectation is not evidence, which is the point of printing the numbers:

    co-tenant       thief present, host keeps headroom, nobody loses much
    host saturation thief present, host runs out
    cgroup cap      no thief, one process loses CPU
    healthy         no thief, no loser

If the table does not show clean separation, the honest outcome is that these three
blueprints cannot be told apart from the scheduler alone, and we say so.

    python3 cpu_cluster_report.py --oncpu <dir> --tasks <task_file> --out cpu_cluster.json
"""
from __future__ import annotations
import argparse, collections, json, os, sys


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oncpu", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", default="cpu_cluster.json")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    rows = []
    for run_id, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.oncpu, f"{run_id}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        s = d.get("signature", {})
        rows.append({"run_id": run_id, "app": app, "family": fam, **s})

    if not rows:
        print("no measurements found")
        return 1

    print(f"\n{'run':40s} {'family':16s} {'util b':>7s} {'util i':>7s} "
          f"{'thief':>16s} {'+cores':>7s} {'loser':>14s} {'-cores':>7s}")
    print("-" * 122)
    for r in rows:
        ub, ui = r.get("host_util_baseline"), r.get("host_util_incident")
        print(f"{r['run_id'][:40]:40s} {r['family']:16s} "
              f"{(ub if ub is not None else 0):7.3f} {(ui if ui is not None else 0):7.3f} "
              f"{str(r.get('thief_comm'))[:16]:>16s} {(r.get('thief_cores_gained') or 0):7.3f} "
              f"{str(r.get('biggest_loser_comm'))[:14]:>14s} "
              f"{(r.get('biggest_loser_cores') or 0):7.3f}")

    # per-family ranges — this is the table that decides whether a rule is writable
    by_fam = collections.defaultdict(list)
    for r in rows:
        by_fam[r["family"]].append(r)

    def rng(vals):
        vals = [v for v in vals if v is not None]
        return (min(vals), max(vals)) if vals else (None, None)

    print(f"\n{'family':16s} {'n':>2s}  {'incident util':>18s}  {'thief cores':>18s}  "
          f"{'loser cores':>18s}  thief seen")
    print("-" * 100)
    summary = []
    for fam, rs in sorted(by_fam.items()):
        u = rng([r.get("host_util_incident") for r in rs])
        t = rng([r.get("thief_cores_gained") for r in rs])
        l = rng([r.get("biggest_loser_cores") for r in rs])
        n_thief = sum(1 for r in rs if r.get("thief_comm"))
        summary.append({"family": fam, "n": len(rs), "util_incident": u,
                        "thief_cores": t, "loser_cores": l, "n_with_thief": n_thief,
                        "thief_comms": sorted({r.get("thief_comm") for r in rs
                                               if r.get("thief_comm")})})
        print(f"{fam:16s} {len(rs):2d}  {u[0]:8.3f}-{u[1]:<9.3f}  "
              f"{t[0]:8.3f}-{t[1]:<9.3f}  {l[0]:8.3f}-{l[1]:<9.3f}  {n_thief}/{len(rs)}")

    print("\nthief process names per family:")
    for s in summary:
        print(f"  {s['family']:16s} {', '.join(s['thief_comms']) or '(none)'}")

    # does any single fact separate the families? report overlaps rather than assert a rule
    print("\nseparation check (overlapping ranges mean the fact alone cannot decide):")
    for key, label in (("util_incident", "host utilisation"),
                       ("thief_cores", "thief cores gained"),
                       ("loser_cores", "loser cores")):
        pairs = []
        for i in range(len(summary)):
            for j in range(i + 1, len(summary)):
                a_, b_ = summary[i][key], summary[j][key]
                if None in a_ or None in b_:
                    continue
                if a_[0] <= b_[1] and b_[0] <= a_[1]:
                    pairs.append(f"{summary[i]['family']}~{summary[j]['family']}")
        print(f"  {label:20s} overlaps: {', '.join(pairs) if pairs else 'NONE - clean split'}")

    json.dump({"rows": rows, "summary": summary}, open(a.out, "w"), indent=2, default=list)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
