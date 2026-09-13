"""Re-derive the thresholds that carry UNITS as dimensionless ones, and measure what it costs.

WHY
---
A threshold with units measures our hardware, not the fault. `THIEF_CORES = 0.5 cores` is a
large share of a 4-core host and noise on a 64-core one. `TX_NEWCOMER_BYTES_PER_S = 3.64 MB/s`
is a lot on a 1 GbE link and nothing on a 25 GbE one. Take the blueprint to a different
machine and the number is wrong in a direction nobody can predict.

We already have one worked example of this failing for real: DISK_IOPS_GAINED = 2000 req/s was
read off one application and scored 1/10 on the other, because the second machine's own
tracing already saturated its disk and capped how large the fault could get.

WHAT THIS DOES
--------------
For each unit-bearing threshold, propose a dimensionless form of the SAME signal, derive a cut
for it the same way (placed against the negatives' extreme, never fitted to the positives),
and report both side by side. Nothing is adopted here - this prints the comparison so the
trade can be judged before anything changes.

    python3 blueprints/lib/derive_dimensionless.py --packs <dir>
"""
import argparse
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD  # noqa: E402


def proc(pack, key):
    return ((pack.get("process") or {}).get("signature") or {}).get(key)


def n_cpus(pack):
    return ((pack.get("oncpu") or {}).get("signature") or {}).get("n_cpus")


# Each entry pairs the threshold we have with a dimensionless version of the same measurement.
# `now` reads the value the current rule uses; `new` reads the proposed replacement.
CANDIDATES = [
    dict(name="THIEF_CORES..BIG_THIEF (band)", owns=["noisy_neighbor"], direction="band",
         now=lambda p: BD._cpu(p)["thief_cores"],
         now_unit="cores",
         new=lambda p: (BD._cpu(p)["thief_cores"] / n_cpus(p)) if n_cpus(p) else None,
         new_unit="share of host cores",
         new_name="THIEF_CORE_SHARE"),
    dict(name="BIG_THIEF", owns=["anomaly_cpu"], direction="above",
         now=lambda p: BD._cpu(p)["thief_cores"],
         now_unit="cores",
         new=lambda p: (BD._cpu(p)["thief_cores"] / n_cpus(p)) if n_cpus(p) else None,
         new_unit="share of host cores",
         new_name="BIG_THIEF_SHARE"),
    dict(name="LOSER_CORES (gate, not a separator)", owns=["svc_cpu_cap"],
         direction="band",
         now=lambda p: BD._cpu(p)["loser_cores"],
         now_unit="cores",
         new=lambda p: (BD._cpu(p)["loser_cores"] / n_cpus(p)) if n_cpus(p) else None,
         new_unit="share of host cores",
         new_name="LOSER_CORE_SHARE"),
    dict(name="FORK_NEWCOMER_PER_S", owns=["fork_storm"], direction="above",
         now=lambda p: proc(p, "fork_newcomer_per_s"),
         now_unit="forks/s",
         new=lambda p: (proc(p, "fork_newcomer_per_s") / proc(p, "forks_per_s_baseline"))
         if proc(p, "forks_per_s_baseline") else None,
         new_unit="x the host's own baseline fork rate",
         new_name="FORK_NEWCOMER_SHARE"),
    dict(name="TX_NEWCOMER_BYTES_PER_S", owns=["data_exfiltration"], direction="above",
         now=lambda p: proc(p, "tx_newcomer_bytes_per_s"),
         now_unit="bytes/s",
         new=lambda p: (proc(p, "tx_newcomer_bytes_per_s") / proc(p, "tx_bytes_per_s_incident"))
         if proc(p, "tx_bytes_per_s_incident") else None,
         new_unit="share of all outbound bytes in the window",
         new_name="TX_NEWCOMER_SHARE"),
    dict(name="EMFILE_PER_S", owns=["fd_exhaustion"], direction="band",
         now=lambda p: proc(p, "emfile_per_s_incident"),
         now_unit="errors/s",
         # EMFILE against a baseline is undefined - it is zero in almost every run, so a ratio
         # divides by zero. Against ALL failing syscalls it is dimensionless and defined
         # everywhere: what share of the failures are descriptor exhaustion.
         new=lambda p: (proc(p, "emfile_per_s_incident")
                        / proc(p, "syscall_errors_per_s_incident"))
         if proc(p, "syscall_errors_per_s_incident") else None,
         new_unit="share of all failing syscalls",
         new_name="EMFILE_ERROR_SHARE"),
]


def cut_and_score(pos, neg, direction):
    """Place the cut against the NEGATIVES' extreme, never fitted to the positives, then
    report the recall it buys. Same rule derive_v2_thresholds.py uses."""
    if not pos:
        return None
    if direction == "band":
        lo, hi = min(pos), max(pos)
        inside = [v for v in neg if lo <= v <= hi]
        return dict(cut="%.4g - %.4g" % (lo, hi), recall=len(pos), n_pos=len(pos),
                    false=len(inside), clean=not inside,
                    margin=None)
    if direction == "above":
        worst = max(neg) if neg else 0.0
        hit = [v for v in pos if v > worst]
        margin = (min(pos) / worst) if (worst and pos) else None
        return dict(cut="> %.4g" % worst, recall=len(hit), n_pos=len(pos), false=0,
                    clean=len(hit) == len(pos), margin=margin)
    worst = min(neg) if neg else 0.0
    hit = [v for v in pos if v < worst]
    margin = (worst / max(pos)) if (max(pos) and worst) else None
    return dict(cut="< %.4g" % worst, recall=len(hit), n_pos=len(pos), false=0,
                clean=len(hit) == len(pos), margin=margin)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    packs = []
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if p.get("run_id"):
            fam = p.get("family_dir") or ""
            p["_family"] = fam[3:] if fam.startswith("tt_") else fam
            packs.append(p)
    print("packs: %d" % len(packs))
    print()

    report = []
    for c in CANDIDATES:
        owns = set(c["owns"])
        rows = []
        for label, get, unit in (("now", c["now"], c["now_unit"]),
                                 ("dimensionless", c["new"], c["new_unit"])):
            pos, neg, missing = [], [], 0
            for p in packs:
                try:
                    v = get(p)
                except Exception:
                    v = None
                if v is None:
                    missing += 1
                    continue
                (pos if p["_family"] in owns else neg).append(float(v))
            r = cut_and_score(pos, neg, c["direction"])
            rows.append((label, unit, r, missing, len(pos), len(neg)))

        print("=== %s   (owns: %s)" % (c["name"], ", ".join(c["owns"])))
        for label, unit, r, missing, np_, nn in rows:
            if not r:
                print("   %-14s no positives" % label)
                continue
            m = ("  margin %.2fx" % r["margin"]) if r.get("margin") else ""
            print("   %-14s %-34s cut %-16s %d/%d positives%s%s"
                  % (label, unit, r["cut"], r["recall"], r["n_pos"], m,
                     "  FALSE INSIDE: %d" % r["false"] if r.get("false") else ""))
            if missing:
                print("   %-14s %d packs could not supply this" % ("", missing))
        a_now, a_new = rows[0][2], rows[1][2]
        if a_now and a_new:
            verdict = ("dimensionless holds" if a_new["recall"] >= a_now["recall"]
                       else "dimensionless LOSES %d of %d"
                            % (a_now["recall"] - a_new["recall"], a_now["n_pos"]))
            print("   -> %s" % verdict)
            report.append(dict(threshold=c["name"], proposed=c["new_name"],
                               proposed_unit=c["new_unit"],
                               now=a_now, dimensionless=a_new, verdict=verdict))
        print()

    if a.out:
        io.open(a.out, "w", encoding="utf-8", newline=chr(10)).write(
            json.dumps({"n_packs": len(packs), "candidates": report}, indent=1) + chr(10))
        print("wrote " + a.out)


if __name__ == "__main__":
    main()
