#!/usr/bin/env python3
"""Rebuild the campaign manifest from the run bundles themselves.

WHY THIS EXISTS
---------------
The campaign manifest is an index, not evidence. The authoritative record of a run lives inside
its bundle: verification.json, meta/event_loss.json, MANIFEST.json.

That distinction stopped being academic 12 runs into the v2 campaign. The driver read the
verdict from $RUN_DIR, which no longer exists once a finished run is moved to the archive, so
every fault run wrote `n/a` into the manifest while its bundle held a perfectly good
`confirmed`. Nothing was lost - but the campaign summary, and the monitoring built on it, were
reporting fiction, and the driver could not be corrected in place because bash reads a running
script incrementally and editing one mid-run can make it execute garbage.

So: derive the index from the bundles, whenever you want, as many times as you like.

    python3 rebuild_manifest.py [--roots DIR ...] [--out FILE]

Defaults to ~/traces and /mnt/archive/runs, printing to stdout.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

FIELDS = ["run_id", "app", "recipe", "intensity", "workload", "repeat",
          "verification", "event_loss", "usable", "total_bytes", "source"]


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:                                                  # noqa: BLE001
        return None


def harvest(run_dir, run_id):
    """Everything the index needs, taken from the bundle rather than from the driver."""
    verif = read_json(os.path.join(run_dir, "verification.json")) or {}
    loss = read_json(os.path.join(run_dir, "meta", "event_loss.json"))
    man = read_json(os.path.join(run_dir, "MANIFEST.json")) or {}
    ident = man.get("identity", {})
    quality = man.get("quality", {})

    if loss is None:
        loss_s = "unrecorded"
    elif loss.get("clean"):
        loss_s = "clean"
    else:
        loss_s = "LOSSY:%d" % loss.get("discarded_events", 0)

    return {
        "run_id": run_id,
        "app": ident.get("app") or ("trainticket" if run_id.startswith("tt_") else "sockshop"),
        "recipe": ident.get("family") or os.path.basename(os.path.dirname(run_dir)),
        "intensity": ident.get("intensity") or "",
        "workload": ident.get("workload") or "",
        "repeat": ident.get("repeat") if ident.get("repeat") is not None else "",
        # verification.json is the authority; MANIFEST.json's copy is a convenience
        "verification": verif.get("verification_status") or quality.get("verification") or "n/a",
        "event_loss": loss_s,
        "usable": quality.get("usable", ""),
        "total_bytes": (man.get("contents") or {}).get("total_bytes", ""),
        "source": run_dir,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="*", default=[os.path.expanduser("~/traces"),
                                                  "/mnt/archive/runs"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows, seen = [], set()
    for root in args.roots:
        if not os.path.isdir(root):
            continue
        for recipe in sorted(os.listdir(root)):
            rdir = os.path.join(root, recipe)
            if not os.path.isdir(rdir):
                continue
            for run_id in sorted(os.listdir(rdir)):
                run_dir = os.path.join(rdir, run_id)
                # A run is a run only if it FINISHED. Anything else is a bundle in flight, and
                # counting it would overstate progress.
                if not os.path.isfile(os.path.join(run_dir, "meta", "runinfo_end.txt")):
                    continue
                if run_id in seen:
                    continue
                seen.add(run_id)
                rows.append(harvest(run_dir, run_id))

    out = open(args.out, "w", newline="") if args.out else sys.stdout
    w = csv.DictWriter(out, fieldnames=FIELDS)
    w.writeheader()
    for r in sorted(rows, key=lambda r: r["run_id"]):
        w.writerow(r)
    if args.out:
        out.close()
        print(f"{len(rows)} runs -> {args.out}", file=sys.stderr)

    # A summary on stderr, so it survives redirecting the CSV to a file.
    from collections import Counter
    print(f"\n{len(rows)} completed runs", file=sys.stderr)
    for field in ("verification", "event_loss"):
        print(f"  {field}:", file=sys.stderr)
        for k, n in Counter(r[field] for r in rows).most_common():
            print(f"    {n:>4}  {k}", file=sys.stderr)
    bad = [r for r in rows if r["recipe"] != "normal"
           and r["verification"] not in ("confirmed", "no_metric_signature")]
    if bad:
        print(f"  fault runs needing review ({len(bad)}):", file=sys.stderr)
        for r in bad[:15]:
            print(f"    {r['run_id']} -> {r['verification']}", file=sys.stderr)


if __name__ == "__main__":
    main()
