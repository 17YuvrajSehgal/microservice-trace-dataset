#!/usr/bin/env python3
"""E1b: replay REAL recorded tool results through both delivery regimes.

Every transcript records, for each tool call, the FULL result object and the string
that was actually sent to the model. So the produced-vs-delivered gap can be measured
on real data without re-running anything and without touching a model.

For each real result we ask the same question under both regimes:
  - is the payload the model receives parseable at all?
  - which top-level keys survive, and how many rows of each?

    python nier-2027/replay_delivery.py
    python nier-2027/replay_delivery.py --csv E1b-replay.csv
"""
from __future__ import annotations
import argparse, collections, glob, importlib, json, os, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "Blueprint", "agent"))

V1_CAP = 6000


def utils(flat_cap: int):
    os.environ["ABL_FLAT_CAP"] = str(flat_cap)
    sys.modules.pop("utils", None)
    return importlib.import_module("utils")


def usable_keys(txt: str):
    """What the model can actually USE. Unparseable payload => nothing."""
    try:
        o = json.loads(txt)
    except Exception:
        return None
    return o if isinstance(o, dict) else {}


def rows_of(o, k):
    v = o.get(k)
    return len(v) if isinstance(v, list) else (1 if v is not None else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts",
                    default=os.path.join(ROOT, "Blueprint", "agent", "transcripts", "v2"))
    ap.add_argument("--csv")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.transcripts, "*.json")))
    calls = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for e in d.get("events") or []:
            if e.get("type") == "tool_execution" and isinstance(e.get("result"), dict):
                calls.append({"file": os.path.basename(f), "tool": e.get("tool"),
                              "result": e["result"], "cap": e.get("sent_cap") or 30000})
    if not calls:
        print("no recorded tool results found", file=sys.stderr)
        return 1

    u_def, u_rep = utils(V1_CAP), None
    # import order matters: reload for the repaired regime
    rows = []
    for c in calls:
        obj, full = c["result"], json.dumps(c["result"], default=str)
        rec = {"file": c["file"], "tool": c["tool"], "chars": len(full),
               "n_keys": len(obj), "keys": list(obj)}
        for label, flat in (("defect", V1_CAP), ("repair", 0)):
            U = utils(flat)
            txt, cut, _ = U.fit_result(obj, c["cap"])
            got = usable_keys(txt)
            rec[f"{label}_valid"] = got is not None
            rec[f"{label}_keys_usable"] = 0 if got is None else len(
                [k for k in obj if k in got])
            rec[f"{label}_truncated"] = bool(cut)
            rec[f"{label}_rows_kept"] = 0 if got is None else sum(
                rows_of(got, k) for k in obj)
            rec[f"{label}_rows_total"] = sum(rows_of(obj, k) for k in obj)
        rows.append(rec)

    n = len(rows)
    print(f"{n} real tool results replayed, from {len(files)} transcripts "
          f"({len({r['file'] for r in rows})} with tool calls)\n")

    print(f"{'':24}{'defect (v1 flat slice)':>26}{'repair (per-tool rows)':>26}")
    print(f"{'':24}{'-'*24:>26}{'-'*24:>26}")
    for label, fn in (
            ("results truncated", lambda r, p: r[f"{p}_truncated"]),
            ("payload UNPARSEABLE", lambda r, p: not r[f"{p}_valid"]),
            ("lost >=1 top-level key", lambda r, p: r[f"{p}_keys_usable"] < r["n_keys"]),
    ):
        d = sum(1 for r in rows if fn(r, "defect"))
        p = sum(1 for r in rows if fn(r, "repair"))
        print(f"{label:24}{f'{d:>5} / {n}  ({100*d/n:4.1f}%)':>26}"
              f"{f'{p:>5} / {n}  ({100*p/n:4.1f}%)':>26}")

    # ---- the positional effect: does delivery depend on where a key sits? ----
    pos = collections.defaultdict(lambda: [0, 0])   # key index -> [delivered, total]
    for r in rows:
        for i, k in enumerate(r["keys"]):
            pos[i][1] += 1
    for c, r in zip(calls, rows):
        U = utils(V1_CAP)
        txt, _, _ = U.fit_result(c["result"], c["cap"])
        got = usable_keys(txt) or {}
        for i, k in enumerate(r["keys"]):
            if k in got:
                pos[i][0] += 1
    print("\ndelivery under the v1 defect, by the key's POSITION in the serialized object:")
    print(f"  {'position':>9}{'delivered':>12}{'calls':>8}   {'rate':>7}")
    for i in sorted(pos)[:10]:
        dlv, tot = pos[i]
        print(f"  {i:>9}{dlv:>12}{tot:>8}   {100*dlv/tot:6.1f}%")

    big = [r for r in rows if r["chars"] > V1_CAP]
    if big:
        print(f"\nof the {len(big)} results larger than the v1 cap "
              f"({100*len(big)/n:.0f}% of all calls):")
        inval = sum(1 for r in big if not r["defect_valid"])
        print(f"  unparseable under the defect : {inval}/{len(big)} "
              f"({100*inval/len(big):.0f}%)")
        print(f"  unparseable under the repair : "
              f"{sum(1 for r in big if not r['repair_valid'])}/{len(big)}")
        print(f"  median size                  : {statistics.median(r['chars'] for r in big):,.0f} chars")

    by_tool = collections.Counter(r["tool"] for r in rows)
    print("\nby tool (calls, median chars, % unparseable under defect):")
    for t, cnt in by_tool.most_common():
        rs = [r for r in rows if r["tool"] == t]
        bad = sum(1 for r in rs if not r["defect_valid"])
        print(f"  {t:<18}{cnt:>5}  {statistics.median(r['chars'] for r in rs):>9,.0f}"
              f"   {100*bad/len(rs):5.1f}%")

    if a.csv:
        import csv
        cols = [c for c in rows[0] if c != "keys"]
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
