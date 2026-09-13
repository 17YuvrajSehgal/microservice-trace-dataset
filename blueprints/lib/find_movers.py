"""Find what actually moves in a fault family, instead of guessing which signals to test.

The first sweep tested 45 signals I picked by hand, and they were mostly host-level
aggregates. That is the wrong instrument for these six faults: an N+1 query problem is about
how many calls an endpoint receives, an event-loop block is about one process going on-CPU,
a DNS delay is about one port. None of those is a host total.

So: walk EVERY numeric field in the pack, compare each family's median against the healthy
control's, and report the biggest movers. Then test the ones the data points at.

    python3 blueprints/lib/find_movers.py --packs <dir> --families code_n_plus_one,dns_delay
"""
import argparse
import collections
import glob
import io
import json
import os

CONTROL = "normal"
SKIP_KEYS = ("timing_s", "total_analysis_s", "analysis_seconds")


def walk(obj, prefix="", out=None, depth=0):
    """Every numeric leaf, as a dotted path. Lists are indexed by their own key where the
    rows carry a name, so `endpoints.slowest[3306].requests_incident` stays comparable across
    runs instead of depending on sort order."""
    if out is None:
        out = {}
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP_KEYS:
                continue
            walk(v, "%s.%s" % (prefix, k) if prefix else k, out, depth + 1)
    elif isinstance(obj, list):
        for row in obj:
            if not isinstance(row, dict):
                continue
            name = (row.get("port") or row.get("endpoint") or row.get("comm")
                    or row.get("service") or row.get("comm_syscall") or row.get("iface"))
            if name is None:
                continue
            walk(row, "%s[%s]" % (prefix, name), out, depth + 1)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out[prefix] = float(obj)
    return out


def med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--families", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--top", type=int, default=14)
    a = ap.parse_args()

    want = set(a.families.split(","))
    vals = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not p.get("run_id") or p.get("app") != a.app:
            continue
        fam = p.get("family_dir") or ""
        fam = fam[3:] if fam.startswith("tt_") else fam
        if fam not in want and fam != CONTROL:
            continue
        for k, v in walk(p).items():
            vals[fam][k].append(v)

    # A field must appear in MOST runs of both groups before it can be compared. The
    # top-by-inflation lists hold whichever processes happened to rank highest, so a name that
    # shows up in one run and not another is list membership changing, not the fault doing
    # something. Without this guard the output is entirely udev-worker and snapd.
    n_ctl = max((len(v) for v in vals[CONTROL].values()), default=0)
    base = {k: med(v) for k, v in vals[CONTROL].items() if len(v) >= 0.6 * n_ctl}
    print("application: %s   control runs: %d"
          % (a.app, len(next(iter(vals[CONTROL].values()), []))))
    print()

    for fam in sorted(want):
        if fam not in vals:
            print("=== %s   NO RUNS" % fam)
            continue
        n = len(next(iter(vals[fam].values()), []))
        print("=== %s   %d runs" % (fam, n))
        moved = []
        for k, vs in vals[fam].items():
            if len(vs) < 0.6 * n:
                continue
            m = med(vs)
            b = base.get(k)
            if m is None or b is None:
                continue
            if b == 0 and m == 0:
                continue
            if b == 0:
                moved.append((float("inf"), k, m, b))
            elif m == 0:
                # fell to zero from a non-zero baseline: a disappearance, and often the
                # clearest thing a fault does
                moved.append((float("inf"), k, m, b))
            else:
                r = m / b
                if r > 1.6 or r < 0.625:
                    moved.append((r if r > 1 else 1.0 / r, k, m, b))
        moved.sort(key=lambda t: -t[0])
        for r, k, m, b in moved[:a.top]:
            rs = ("went to 0" if (r == float("inf") and b) else
                  "only in fault" if r == float("inf") else "%.3gx" % r)
            print("   %-58s %-14s %s -> %s"
                  % (k[:58], rs, ("%.4g" % b) if b is not None else "-", "%.4g" % m))
        if not moved:
            print("   nothing moved more than 1.6x against the healthy control")
        print()


if __name__ == "__main__":
    main()
