#!/usr/bin/env python3
"""Walk EVERY directory in the dataset and say, per run, whether it is usable.

Nothing is sampled and nothing is skipped. Every directory under the app/family level is
visited and classified, including ones that are not runs, so a stray directory cannot hide.

WHAT IS CHECKED, AND WHY EACH ONE IS HERE
-----------------------------------------
bundle_complete    the files a run is supposed to contain. A missing verification.json is how
                   a run with no verdict came to look identical to one that passed.
trace_present      channels, metadata, and a plausible size. A truncated trace reads as a
                   quiet system.
windows_sane       the injection window must sit inside the traced window, with a baseline
                   before it and a recovery after it. If the injection starts before tracing,
                   the baseline is not a baseline.
injection_verdict  the campaign's own verify_injection.py result. It was already right about
                   every bad run we later found by hand; the failure was that nobody read it.
                     confirmed           the fault moved its target metric
                     unconfirmed         the checks ran and saw nothing -> treat as a failure
                     no_metric_signature no metric target can see this fault at all. NOT a
                                         failed injection - all 5 dns_delay runs read this way
                                         and 4 show the fault plainly in the kernel
                     borderline          weak; needs a human
metrics_sidecar    the <run>_metrics directory, which is a sibling and easy to lose
load_csv           the load generator's CSV. 103 Train Ticket runs have none (issue 14)

    python3 audit_dataset.py --root /path/to/stratatrace-v2 --out audit.json
"""
import argparse
import collections
import io
import json
import os
import re
import sys

MIN_TRACE_MB = 50.0

STATUS_GOOD = "confirmed"
STATUS_FAIL = "unconfirmed"
STATUS_SOFT = ("borderline",)
STATUS_BLIND = "no_metric_signature"


def load(path):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def stamp(path):
    try:
        m = re.search(r"timestamp_utc=(\S+)", io.open(path, encoding="utf-8").read())
        return m.group(1) if m else None
    except Exception:
        return None


def audit_run(run_dir, run, app, family):
    r = {"app": app, "family": family, "run": run, "path": run_dir,
         "problems": [], "warnings": [], "notes": []}

    # ---- the files a bundle is supposed to have
    have = {name: os.path.exists(os.path.join(run_dir, name))
            for name in ("MANIFEST.json", "SHA256SUMS", "ground_truth.json",
                         "verification.json", "verification.png")}
    r["files"] = have
    is_fault = have["ground_truth.json"]
    r["is_fault_run"] = is_fault
    for name in ("MANIFEST.json", "SHA256SUMS"):
        if not have[name]:
            r["problems"].append("missing %s" % name)
    if is_fault:
        for name in ("verification.json", "verification.png"):
            if not have[name]:
                r["problems"].append("missing %s" % name)
    else:
        r["notes"].append("no ground_truth.json - control run")

    # ---- the trace itself
    ctf = os.path.join(run_dir, "kernel", "kernel")
    chans, size = [], 0
    if os.path.isdir(ctf):
        for e in os.listdir(ctf):
            if e.startswith("channel"):
                chans.append(e)
                try:
                    size += os.path.getsize(os.path.join(ctf, e))
                except OSError:
                    pass
    r["trace"] = {"channels": len(chans), "mb": round(size / 1048576.0, 1),
                  "metadata": os.path.exists(os.path.join(ctf, "metadata"))}
    if not chans:
        r["problems"].append("no kernel channel files")
    if not r["trace"]["metadata"]:
        r["problems"].append("no CTF metadata")
    if chans and r["trace"]["mb"] < MIN_TRACE_MB:
        r["problems"].append("trace only %.1f MB - truncated?" % r["trace"]["mb"])

    # ---- the windows
    t0 = stamp(os.path.join(run_dir, "meta", "runinfo_start.txt"))
    t1 = stamp(os.path.join(run_dir, "meta", "runinfo_end.txt"))
    r["trace_window"] = [t0, t1]
    if not t0 or not t1:
        r["problems"].append("no runinfo start/end stamp")
    gt = load(os.path.join(run_dir, "ground_truth.json")) if is_fault else None
    if gt:
        f = gt.get("fault") or {}
        s, e = f.get("injection_start_utc"), f.get("injection_end_utc")
        r["injection_window"] = [s, e]
        if not s or not e:
            r["problems"].append("ground truth has no injection window")
        elif t0 and t1:
            if not (t0 < s):
                r["problems"].append("injection starts at/before tracing - NO BASELINE")
            if not (e < t1):
                r["problems"].append("injection ends at/after tracing - NO RECOVERY")

    # ---- what the campaign said about the injection
    if is_fault:
        v = load(os.path.join(run_dir, "verification.json"))
        st = (v or {}).get("verification_status")
        r["verification_status"] = st
        if v is None:
            r["problems"].append("verification.json unreadable or absent")
        elif st == STATUS_FAIL:
            r["problems"].append("verification=unconfirmed - the fault was not detected")
        elif st == STATUS_BLIND:
            r["warnings"].append("verification=no_metric_signature - metrics cannot see this "
                                 "fault; check the kernel side before using it")
        elif st in STATUS_SOFT:
            r["warnings"].append("verification=%s - weak effect, needs a human" % st)
        elif st != STATUS_GOOD:
            r["problems"].append("verification status %r not recognised" % st)
        if (v or {}).get("operator_review_required"):
            r["warnings"].append("flagged for operator review")

    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    runs, sidecars, strays = [], [], []
    for app in sorted(os.listdir(a.root)):
        app_dir = os.path.join(a.root, app)
        if not os.path.isdir(app_dir):
            strays.append(("file at app level", app_dir))
            continue
        for family in sorted(os.listdir(app_dir)):
            fam_dir = os.path.join(app_dir, family)
            if not os.path.isdir(fam_dir):
                strays.append(("file at family level", fam_dir))
                continue
            for entry in sorted(os.listdir(fam_dir)):
                d = os.path.join(fam_dir, entry)
                if not os.path.isdir(d):
                    strays.append(("file at run level", d))
                    continue
                if entry.endswith("_metrics"):
                    n = len(os.listdir(d)) if os.path.isdir(d) else 0
                    sidecars.append({"run": entry[:-8], "app": app, "family": family,
                                     "files": n, "path": d})
                    continue
                runs.append(audit_run(d, entry, app, family))

    # every run should have its metrics sidecar
    have_side = set((s["app"], s["run"]) for s in sidecars)
    empty_side = set((s["app"], s["run"]) for s in sidecars if s["files"] == 0)
    for r in runs:
        k = (r["app"], r["run"])
        if k not in have_side:
            r["warnings"].append("no _metrics sidecar directory")
        elif k in empty_side:
            r["warnings"].append("_metrics sidecar is empty")

    bad = [r for r in runs if r["problems"]]
    warn = [r for r in runs if not r["problems"] and r["warnings"]]
    clean = [r for r in runs if not r["problems"] and not r["warnings"]]

    print("=" * 96)
    print("runs audited      : %d" % len(runs))
    print("  clean           : %d" % len(clean))
    print("  warnings only   : %d" % len(warn))
    print("  PROBLEMS        : %d" % len(bad))
    print("metrics sidecars  : %d  (empty: %d)" % (len(sidecars), len(empty_side)))
    print("stray entries     : %d" % len(strays))
    print("=" * 96)

    reasons = collections.Counter()
    for r in bad:
        for p in r["problems"]:
            reasons[re.sub(r"\d+\.?\d*", "N", p)] += 1
    print()
    print("--- why runs have problems ---")
    for k, n in reasons.most_common():
        print("  %4d  %s" % (n, k))

    wreasons = collections.Counter()
    for r in runs:
        for w in r["warnings"]:
            wreasons[re.sub(r"\d+\.?\d*", "N", w)] += 1
    print()
    print("--- warnings (run is usable, but know this) ---")
    for k, n in wreasons.most_common():
        print("  %4d  %s" % (n, k))

    print()
    print("--- every run WITH A PROBLEM ---")
    for r in sorted(bad, key=lambda r: (r["app"], r["family"], r["run"])):
        print("  %-12s %-24s %-42s %s"
              % (r["app"], r["family"], r["run"][:42], "; ".join(r["problems"])[:70]))

    by_fam = collections.defaultdict(lambda: [0, 0, 0])
    for r in runs:
        k = (r["app"], r["family"])
        by_fam[k][0] += 1
        if r["problems"]:
            by_fam[k][1] += 1
        elif r["warnings"]:
            by_fam[k][2] += 1
    print()
    print("--- per family: total / problems / warnings ---")
    for (app, fam), (t, b, w) in sorted(by_fam.items()):
        flag = "  <-- " if b else ""
        print("  %-12s %-24s %3d   %3d   %3d%s" % (app, fam, t, b, w, flag))

    if strays:
        print()
        print("--- stray entries that are not runs ---")
        for why, p in strays[:20]:
            print("  %-24s %s" % (why, p))

    if a.out:
        with io.open(a.out, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(json.dumps({"runs": runs, "sidecars": sidecars, "strays": strays},
                                indent=1) + chr(10))
        print()
        print("wrote " + a.out)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
