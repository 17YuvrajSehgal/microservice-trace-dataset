#!/usr/bin/env python3
"""Compare two analysis outputs by VALUE, not by row order.

net_loss_signature sorts interfaces by retrans_pct. On a healthy run almost every interface
is 0.0, so they all tie, and tied rows keep whatever order the interfaces first appeared in
the event stream. A raw `diff` therefore reports a difference when nothing measured changed.

This keys every per-interface row by its interface name and compares the numbers, so a real
disagreement is separated from a reshuffle.

    python3 canon_compare.py old.json new.json
"""
from __future__ import annotations
import json, sys


def rows_by_iface(o, out=None, path="root"):
    """Every dict carrying an 'iface' key, keyed by (where it sits, iface name)."""
    out = {} if out is None else out
    if isinstance(o, dict):
        if "iface" in o:
            out[(path, o["iface"])] = {k: v for k, v in o.items() if k != "iface"}
        for k, v in o.items():
            rows_by_iface(v, out, f"{path}.{k}")
    elif isinstance(o, list):
        for v in o:
            rows_by_iface(v, out, path)
    return out


def scalars(o, out=None, path="root"):
    """Every non-container value that is NOT inside an iface row - the decision inputs."""
    out = {} if out is None else out
    if isinstance(o, dict):
        if "iface" in o:
            return out
        for k, v in o.items():
            scalars(v, out, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            scalars(v, out, f"{path}[{i}]")
    else:
        out[path] = o
    return out


def main():
    a, b = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
    ra, rb = rows_by_iface(a), rows_by_iface(b)

    only_a, only_b = set(ra) - set(rb), set(rb) - set(ra)
    diffs = [(k, ra[k], rb[k]) for k in set(ra) & set(rb) if ra[k] != rb[k]]

    print(f"interface rows: {len(ra)} vs {len(rb)}")
    if only_a:
        print(f"  only in first  ({len(only_a)}): {sorted(x[1] for x in only_a)[:6]}")
    if only_b:
        print(f"  only in second ({len(only_b)}): {sorted(x[1] for x in only_b)[:6]}")
    if diffs:
        print(f"  VALUES DIFFER on {len(diffs)} interface(s):")
        for k, x, y in diffs[:6]:
            keys = [f for f in x if x.get(f) != y.get(f)]
            print(f"    {k[1]:22s} {k[0]}")
            for f in keys[:4]:
                print(f"      {f}: {x.get(f)} -> {y.get(f)}")
    if not (only_a or only_b or diffs):
        print("  per-interface values: IDENTICAL (row order may differ, and does not matter)")

    sa, sb = scalars(a), scalars(b)
    sdiff = {k: (sa[k], sb[k]) for k in set(sa) & set(sb) if sa[k] != sb[k]}
    # paths that merely index into a reordered list are not real differences
    real = {k: v for k, v in sdiff.items() if "[" not in k}
    print(f"\nscalar fields: {len(sa)} vs {len(sb)}, {len(sdiff)} differ "
          f"({len(real)} outside reordered lists)")
    for k, (x, y) in list(real.items())[:12]:
        print(f"  {k}: {x} -> {y}")

    ok = not (only_a or only_b or diffs or real)
    print(f"\nVERDICT: {'EQUIVALENT' if ok else 'REAL DIFFERENCE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
