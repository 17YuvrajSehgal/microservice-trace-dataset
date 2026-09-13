"""Can we tell a broken dependency from badly written code that calls it?

WHY THIS MATTERS
----------------
Measured over 272 runs, the datastore blueprint fires on FIVE anti-pattern families it does
not own - code_serial_awaits, code_event_loop_block, code_unbounded_cache, code_lock_across_io,
code_n_plus_one - plus conn_pool_exhaustion and dns_delay. Fourteen runs where the engine says
"the datastore is slow" and the datastore is fine.

It is not wrong that something is waiting. A service doing serial awaits IS waiting. What is
wrong is the cause it names, and that is the whole difference between detection and root cause.

THE IDEA THAT DID NOT WORK
--------------------------
"An anti-pattern is present in the baseline window too; a fault only appears in the incident
window." Reasonable, and untestable on our data: code_defect_lib.sh restarts the container
with STRATA_BUG set at the incident boundary, so in our runs the defect is absent from the
baseline exactly like a fault. Recorded rather than quietly dropped - it may still be the
right test on production data, where an anti-pattern really has always been there.

WHAT THIS MEASURES INSTEAD
--------------------------
The mechanism, not the timing. Extra waiting has three possible sources and they are
distinguishable in principle:

    calls got SLOWER     -> the thing being called is the problem      (a real dependency fault)
    there were MORE calls -> the CALLER is the problem                 (N+1, retry storms)
    same calls, less overlap -> the caller serialised them             (serial awaits)

`endpoints.slowest` carries requests_baseline and requests_incident as well as p50, so the
first two are directly measurable per run.

    python3 blueprints/lib/measure_antipattern.py --packs <dir>
"""
import argparse
import collections
import glob
import io
import json
import os

# Families the datastore blueprint owns, against the ones it wrongly fires on.
OWNED = {"slow_db"}
IMPOSTORS = {"code_serial_awaits", "code_event_loop_block", "code_unbounded_cache",
             "code_lock_across_io", "code_n_plus_one", "conn_pool_exhaustion", "dns_delay"}
CONTROL = {"normal"}


def sig(pack, sec):
    return ((pack.get(sec) or {}).get("signature") or {})


def measures(pack):
    """Per-call latency against call count, for the endpoint that slowed most."""
    s = sig(pack, "endpoints").get("slowest") or {}
    rb, ri = s.get("requests_baseline"), s.get("requests_incident")
    p50b, p50i = s.get("p50_baseline_ms"), s.get("p50_incident_ms")
    out = {}
    if rb:
        out["requests_x"] = ri / float(rb)
    if p50b:
        out["per_call_x"] = p50i / float(p50b)
    # The deciding shape: does the extra time come from slower calls or from more of them?
    if out.get("per_call_x") and out.get("requests_x"):
        out["slower_vs_more"] = out["per_call_x"] / out["requests_x"]
    # Whole-window work: sum over every endpoint we kept, not just the worst one.
    rows = (pack.get("endpoints") or {}).get("slowest") or []
    tb = sum(r.get("requests_baseline") or 0 for r in rows)
    ti = sum(r.get("requests_incident") or 0 for r in rows)
    if tb:
        out["total_requests_x"] = ti / float(tb)
    return out


def rng(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return "-"
    return "%.4g .. %.4g" % (vals[0], vals[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not p.get("run_id"):
            continue
        fam = p.get("family_dir") or ""
        fam = fam[3:] if fam.startswith("tt_") else fam
        for k, v in measures(p).items():
            by[fam][k].append(v)

    keys = ["per_call_x", "requests_x", "slower_vs_more", "total_requests_x"]
    groups = [("OWNED (a real dependency fault)", OWNED),
              ("IMPOSTORS (fire on the datastore blueprint but should not)", IMPOSTORS),
              ("CONTROL", CONTROL)]
    print("%-24s %-22s %-22s %-22s" % ("family", "per-call latency x", "call count x",
                                       "slower / more"))
    print("-" * 96)
    for title, fams in groups:
        print(title)
        for fam in sorted(fams):
            if fam not in by:
                continue
            print("  %-22s %-22s %-22s %-22s"
                  % (fam, rng(by[fam]["per_call_x"]), rng(by[fam]["requests_x"]),
                     rng(by[fam]["slower_vs_more"])))
        print()

    # Does any single cut separate the owned family from the impostors?
    print("SEPARATION")
    for k in keys:
        pos = [v for f in OWNED for v in by[f][k]]
        neg = [v for f in IMPOSTORS for v in by[f][k]]
        if not pos or not neg:
            continue
        lo_p, hi_n = min(pos), max(neg)
        hi_p, lo_n = max(pos), min(neg)
        if lo_p > hi_n:
            print("  %-18s separates ABOVE: lowest owned %.4g > highest impostor %.4g "
                  "(margin %.2fx)" % (k, lo_p, hi_n, lo_p / hi_n if hi_n else float("inf")))
        elif hi_p < lo_n:
            print("  %-18s separates BELOW: highest owned %.4g < lowest impostor %.4g "
                  "(margin %.2fx)" % (k, hi_p, lo_n, lo_n / hi_p if hi_p else float("inf")))
        else:
            inside = sum(1 for v in neg if lo_p <= v <= hi_p)
            print("  %-18s OVERLAPS: owned %.4g..%.4g, %d of %d impostor runs inside"
                  % (k, lo_p, hi_p, inside, len(neg)))

    if a.out:
        io.open(a.out, "w", encoding="utf-8", newline=chr(10)).write(
            json.dumps({f: {k: v for k, v in d.items()} for f, d in by.items()}, indent=1)
            + chr(10))
        print(chr(10) + "wrote " + a.out)


if __name__ == "__main__":
    main()
