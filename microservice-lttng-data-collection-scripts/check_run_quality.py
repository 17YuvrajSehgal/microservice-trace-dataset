#!/usr/bin/env python3
"""One gate at the end of a run: is this bundle usable, and if not, why.

WHY THIS EXISTS
---------------
Two whole classes of bad run reached the v2 dataset and were not noticed for months.

1. FAILED INJECTIONS WERE KEPT. `verify_injection.py` did its job - it marked
   dns_delay r4 `no_metric_signature`, and every tt_svc_cpu_cap run `unconfirmed`. Nothing
   acted on that. The bundles shipped, and later analysis used them as positives. The campaign
   had the answer the whole time and no step read it.

2. CONTAMINATED BASELINES WERE INVISIBLE. The code-defect recipes restarted the container
   inside the baseline window, putting 28-80% retransmission in a window that should read
   0.00%. Nothing looked at the baseline at all, so 25 runs were collected before anyone saw
   it - and only then from the analysis side, months later.

Both are cheap to catch at collection time, on the VM, while it is still possible to re-run.
That is all this does.

    python3 check_run_quality.py --run-dir ~/traces/<recipe>/<run> [--strict]

Exit code 0 = usable, 1 = not usable. `--strict` also fails on a warning.
"""
import argparse
import glob
import io
import json
import os
import re
import sys

# A healthy baseline measured 0.00% retransmission in all 40 runs we have checked by hand, and
# 0-5.6% across all 272 v2 packs. 10% is far above anything legitimate and far below the
# 28-80% a container restart produces, so it separates the two without being fussy.
BASELINE_RETRANS_MAX_PCT = 10.0

# A restart also makes endpoints disappear as containers return on new addresses: 3-7 gone in
# every contaminated run, against 1-2 in a clean one.
BASELINE_ENDPOINTS_GONE_MAX = 3

# The four verdicts verify_injection.py can produce, and what each one means for USABILITY.
#
# The distinction that matters, and that I got wrong first time:
#
#   unconfirmed          the metric checks RAN and did not see the fault. Treat as a failure -
#                        this run probably does not contain what it claims.
#   no_metric_signature  no metric target could see this fault AT ALL. That is NOT a failed
#                        injection. Measured across v2: all 5 dns_delay runs are
#                        no_metric_signature, and 4 of them show 161-310 EMFILE/s in the kernel
#                        trace. The fault happened; Prometheus simply cannot see it. For a
#                        kernel-tracing project that is a result, not a defect - so this must
#                        be checked against the kernel side, never auto-failed.
#   borderline           the checks ran and the effect is weak. Needs a human.
#   confirmed            the fault moved its target metric.
GOOD_STATUS = ("confirmed",)
SOFT_STATUS = ("borderline", "no_metric_signature")
BAD_STATUS = ("unconfirmed",)


def read_json(path):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def check_injection(run_dir, out):
    """Did the fault actually take? The campaign already answers this; read the answer."""
    gt = read_json(os.path.join(run_dir, "ground_truth.json"))
    if gt is None:
        out["checks"].append({"name": "ground_truth_present", "ok": None,
                              "detail": "no ground_truth.json - normal/control run, or the "
                                        "recipe never stamped one"})
        return
    v = read_json(os.path.join(run_dir, "verification.json"))
    if v is None:
        out["checks"].append({
            "name": "injection_verified", "ok": False,
            "detail": "ground_truth.json exists but verification.json does not. The verify "
                      "step did not run or crashed - it is wrapped in `|| true`, so it fails "
                      "silently."})
        return
    st = v.get("verification_status")
    if st in GOOD_STATUS:
        ok, detail = True, "verification_status=confirmed"
    elif st == "no_metric_signature":
        ok, detail = None, (
            "verification_status=no_metric_signature - no metric target can see this fault. "
            "This is NOT a failed injection. CHECK THE KERNEL SIDE before deciding: if the "
            "trace shows the effect, the run is good and the finding is that metrics missed "
            "it. All 5 dns_delay runs read this way and 4 of them show the fault clearly in "
            "the kernel.")
    elif st in SOFT_STATUS:
        ok, detail = None, ("verification_status=%s - the effect is weak. Needs a human before "
                            "this run is used as a positive." % st)
    else:
        ok, detail = False, (
            "verification_status=%s - the metric checks ran and did not see the fault. This "
            "run probably does not contain what it claims and must not be used as a "
            "positive." % st)
    out["checks"].append({"name": "injection_verified", "ok": ok, "detail": detail,
                          "verification_status": st})


def check_baseline(run_dir, out):
    """Is the baseline window actually quiet? A restart or a leftover fault makes it loud."""
    # The meta directory records per-interface counters at the run boundaries. Where the
    # analysis pack is not available yet, fall back to whatever the run itself carries.
    nl = None
    for cand in ("netloss.json", "meta/netloss_baseline.json"):
        nl = read_json(os.path.join(run_dir, cand))
        if nl:
            break
    if not nl:
        out["checks"].append({
            "name": "baseline_quiet", "ok": None,
            "detail": "no per-interface baseline counters in the bundle; run the pack builder "
                      "and re-check, or accept that this gate did not run"})
        return
    worst = 0.0
    for row in (nl.get("worst") or []):
        worst = max(worst, row.get("retrans_pct_baseline") or 0.0)
    ok = worst <= BASELINE_RETRANS_MAX_PCT
    out["checks"].append({
        "name": "baseline_quiet", "ok": ok,
        "detail": "worst baseline retransmission %.3g%% (bar %.3g%%)%s" % (
            worst, BASELINE_RETRANS_MAX_PCT,
            "" if ok else " - something disruptive happened INSIDE the baseline window. A "
                          "container restart does exactly this. Every baseline-relative "
                          "measurement in this run is against a broken reference.")})


def check_windows(run_dir, out):
    """Does the ground truth put the injection inside the traced window, with room either side?"""
    gt = read_json(os.path.join(run_dir, "ground_truth.json"))
    if not gt:
        return
    f = gt.get("fault") or {}
    s, e = f.get("injection_start_utc"), f.get("injection_end_utc")
    if not s or not e:
        out["checks"].append({"name": "injection_window_stamped", "ok": False,
                              "detail": "ground truth has no injection start/end"})
        return
    out["checks"].append({"name": "injection_window_stamped", "ok": True,
                          "detail": "%s .. %s" % (s, e)})

    start = os.path.join(run_dir, "meta", "runinfo_start.txt")
    end = os.path.join(run_dir, "meta", "runinfo_end.txt")
    ts = {}
    for tag, p in (("start", start), ("end", end)):
        try:
            m = re.search(r"timestamp_utc=(\S+)", io.open(p, encoding="utf-8").read())
            if m:
                ts[tag] = m.group(1)
        except Exception:
            pass
    if len(ts) == 2:
        inside = ts["start"] < s and e < ts["end"]
        out["checks"].append({
            "name": "injection_inside_trace", "ok": inside,
            "detail": "trace %s .. %s" % (ts["start"], ts["end"]) + (
                "" if inside else " - the injection is NOT fully inside the traced window")})


def check_trace(run_dir, out):
    """Is there a readable trace with actual content?"""
    ctf = os.path.join(run_dir, "kernel", "kernel")
    chans = glob.glob(os.path.join(ctf, "channel0_*"))
    meta = os.path.exists(os.path.join(ctf, "metadata"))
    size = sum(os.path.getsize(c) for c in chans) if chans else 0
    ok = bool(chans) and meta and size > 1024 * 1024
    out["checks"].append({
        "name": "trace_readable", "ok": ok,
        "detail": "%d channel files, metadata=%s, %.1f MB" % (len(chans), meta,
                                                              size / 1048576.0)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--strict", action="store_true",
                    help="treat a check that could not run as a failure")
    a = ap.parse_args()

    out = {"run_dir": a.run_dir, "run": os.path.basename(a.run_dir.rstrip("/")), "checks": []}
    check_trace(a.run_dir, out)
    check_windows(a.run_dir, out)
    check_injection(a.run_dir, out)
    check_baseline(a.run_dir, out)

    failed = [c for c in out["checks"] if c["ok"] is False]
    unknown = [c for c in out["checks"] if c["ok"] is None]
    out["usable"] = not failed and not (a.strict and unknown)
    if out["usable"]:
        out["verdict"] = "usable"
    elif failed:
        out["verdict"] = "NOT USABLE: " + "; ".join(c["name"] for c in failed)
    else:
        out["verdict"] = ("NOT USABLE under --strict: these checks could not run: "
                          + "; ".join(c["name"] for c in unknown))

    print("=== %s" % out["run"])
    for c in out["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["ok"] is False else "?   ")
        print("  %s %-26s %s" % (mark, c["name"], c["detail"][:120]))
    print("  -> %s" % out["verdict"])

    dest = a.out or os.path.join(a.run_dir, "run_quality.json")
    try:
        with io.open(dest, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(json.dumps(out, indent=2) + chr(10))
    except Exception as e:
        print("  (could not write %s: %s)" % (dest, e))
    return 0 if out["usable"] else 1


if __name__ == "__main__":
    sys.exit(main())
