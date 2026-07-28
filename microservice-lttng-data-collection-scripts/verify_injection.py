#!/usr/bin/env python3
"""Injection verification: did an injected fault actually move its declared
target metric(s)?  (Phase-1 per-run QC; fault_catalog.md §6.)

Reads a run's ground-truth (for the injection window) and the pre-registered
target-metric panel (faults/verification_targets.json), queries Prometheus
over baseline / injection / recovery windows, and writes a
confirmed|borderline|unconfirmed verdict to verification.json (plus an
optional impact PNG if matplotlib is present).

Stdlib only for the core (urllib for Prometheus); matplotlib optional.

Usage:
  # against a live Prometheus, using a run's ground_truth.json:
  python3 verify_injection.py --ground-truth ~/fault-state/slow_db_catalogue.ground_truth.json \
      --prometheus http://localhost:9090 --out ~/traces/.../verification.json

  # offline self-test of the analysis math (no network, no Prometheus):
  python3 verify_injection.py --self-test
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TARGETS = os.path.join(_HERE, "faults", "verification_targets.json")
EPS = 1e-9


def parse_utc(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


# --------------------------------------------------------------- prometheus --

def query_prometheus(prom_url, promql, start_epoch, end_epoch, step="5s"):
    """Return [(epoch_float, value_float), ...] for a single-series query_range.
    If the query yields multiple series, they are summed per timestamp (the
    target PromQL is expected to aggregate to one series, but be defensive)."""
    q = urllib.parse.urlencode({
        "query": promql, "start": int(start_epoch),
        "end": int(end_epoch), "step": step})
    url = f"{prom_url}/api/v1/query_range?{q}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        doc = json.load(resp)
    if doc.get("status") != "success":
        raise RuntimeError(f"prometheus error: {doc.get('error', doc.get('status'))}")
    result = doc.get("data", {}).get("result", [])
    merged = {}
    for series in result:
        for ts, val in series.get("values", []):
            try:
                merged[float(ts)] = merged.get(float(ts), 0.0) + float(val)
            except (TypeError, ValueError):
                pass
    return sorted(merged.items())


# ------------------------------------------------------------------ analysis --

def _stats(vals):
    if not vals:
        return 0.0, 0.0
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return mean, var ** 0.5


def analyze(samples, t_start, t_end, baseline_s, recovery_s, target, settle_s=0):
    """Pure verdict for one target metric.

    samples: [(epoch, value)]; t_start/t_end: injection window epochs.
    settle_s: skip this many seconds at the START of the injection window when
      computing injection stats. Rate-windowed metrics (e.g. a p95 over
      rate(..[1m])) take ~one rate-window to ramp after onset, so the first
      part of the injection window still averages in pre-injection samples and
      dilutes the signal. Skipping the settling period makes the injection
      stats reflect the settled fault state. Capped at half the window so short
      injections still yield samples.
    Returns a dict with the per-window stats and a per-target pass/fail.
    """
    settle = min(settle_s, (t_end - t_start) * 0.5)
    base = [v for ts, v in samples if t_start - baseline_s <= ts < t_start]
    inj = [v for ts, v in samples if t_start + settle <= ts <= t_end]
    rec = [v for ts, v in samples if t_end < ts <= t_end + recovery_s]

    b_mean, b_std = _stats(base)
    i_mean, _ = _stats(inj)
    r_mean, _ = _stats(rec)

    direction = target.get("direction", "increase")
    abs_thr = target.get("abs_threshold")
    sig_thr = target.get("threshold_sigma", 3)
    frac_thr = target.get("min_fraction", 0.6)

    signed_delta = i_mean - b_mean
    delta_sigma = signed_delta / b_std if b_std > EPS else None

    if direction == "increase":
        direction_ok = i_mean > b_mean
        above = [v for v in inj if abs_thr is None or v >= abs_thr]
        sigma_ok = (delta_sigma is not None and delta_sigma >= sig_thr)
    else:  # decrease
        direction_ok = i_mean < b_mean
        above = [v for v in inj if abs_thr is None or v <= abs_thr]
        sigma_ok = (delta_sigma is not None and delta_sigma <= -sig_thr)

    fraction = (len(above) / len(inj)) if inj else 0.0
    # When the baseline is essentially flat (std ~ 0), sigma is undefined /
    # infinite; fall back to the absolute-threshold gate.
    if delta_sigma is None:
        sigma_ok = fraction >= frac_thr and direction_ok
    fraction_ok = fraction >= frac_thr

    passed = bool(direction_ok and fraction_ok and (sigma_ok or abs_thr is None))
    return {
        "name": target.get("name"),
        "promql": target.get("promql"),
        "canonical": target.get("canonical", False),
        "direction": direction,
        "baseline_mean": round(b_mean, 6), "baseline_std": round(b_std, 6),
        "injection_mean": round(i_mean, 6), "recovery_mean": round(r_mean, 6),
        "delta_sigma": (round(delta_sigma, 3) if delta_sigma is not None else None),
        "fraction_above_threshold": round(fraction, 3),
        "n_baseline": len(base), "n_injection": len(inj), "n_recovery": len(rec),
        "direction_ok": direction_ok, "sigma_ok": sigma_ok,
        "fraction_ok": fraction_ok, "passed": passed,
    }


def overall_verdict(checks):
    """confirmed if the canonical target passes; borderline if it has the
    right direction and coverage but a sub-threshold magnitude; else
    unconfirmed. Runs with no canonical target fall back to 'any passed'."""
    canon = [c for c in checks if c["canonical"]] or checks
    if not canon:
        return "unconfirmed"
    c = canon[0]
    if c["passed"]:
        return "confirmed"
    if c["direction_ok"] and c["fraction_ok"]:
        return "borderline"
    return "unconfirmed"


# ----------------------------------------------------------------- plotting --

def try_plot(out_png, series_by_name, t_start, t_end):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except Exception:
        return None
    fig, axes = plt.subplots(len(series_by_name), 1, sharex=True,
                             figsize=(9, 2.4 * len(series_by_name)), squeeze=False)
    for ax, (name, samples) in zip(axes[:, 0], series_by_name.items()):
        xs = [dt.datetime.fromtimestamp(ts, UTC) for ts, _ in samples]
        ys = [v for _, v in samples]
        ax.plot(xs, ys, lw=1.2)
        ax.axvspan(dt.datetime.fromtimestamp(t_start, UTC),
                   dt.datetime.fromtimestamp(t_end, UTC), alpha=0.15, color="red")
        ax.set_ylabel(name, fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    axes[-1, 0].set_xlabel("time (injection window shaded)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=90)
    plt.close(fig)
    return out_png


# --------------------------------------------------------------------- main --

def run_verification(gt, targets_all, prom_url, step, out_json, out_png):
    fault = gt["fault"]
    name = fault["name"]
    if fault.get("injection_end_utc") in (None, "null"):
        sys.exit(f"ground truth for {name} has no injection_end_utc (run not closed?)")
    t_start = parse_utc(fault["injection_start_utc"]).timestamp()
    t_end = parse_utc(fault["injection_end_utc"]).timestamp()

    targets = targets_all.get(name)
    if not targets:
        sys.exit(f"no verification targets registered for fault '{name}'")
    win = targets_all.get("_windows", {})
    baseline_s = win.get("baseline_s", 60)
    recovery_s = win.get("recovery_s", 60)
    settle_s = win.get("settle_s", 30)

    checks, series_by_name = [], {}
    for t in targets:
        samples = query_prometheus(
            prom_url, t["promql"],
            t_start - baseline_s - 15, t_end + recovery_s + 15, step)
        series_by_name[t["name"]] = samples
        checks.append(analyze(samples, t_start, t_end, baseline_s, recovery_s, t, settle_s))

    verdict = overall_verdict(checks)
    result = {
        "fault": name,
        "injection_window_utc": [fault["injection_start_utc"], fault["injection_end_utc"]],
        "verification_status": verdict,
        "operator_review_required": verdict == "borderline",
        "checks": checks,
    }
    if out_png:
        p = try_plot(out_png, series_by_name, t_start, t_end)
        result["impact_plot"] = p
    if out_json:
        with open(out_json, "w") as f:
            json.dump(result, f, indent=2)
    return result


def _series(t0, t1, base, inj, post, step=5, span=60):
    out = []
    for ts in range(int(t0 - span), int(t1 + span), step):
        out.append((float(ts), base if ts < t0 else (inj if ts <= t1 else post)))
    return out


def _noisy_series(t0, t1, base_vals, inj, post, step=5, span=60):
    out, i = [], 0
    for ts in range(int(t0 - span), int(t0), step):
        out.append((float(ts), base_vals[i % len(base_vals)])); i += 1
    for ts in range(int(t0), int(t1) + step, step):
        out.append((float(ts), inj))
    for ts in range(int(t1) + step, int(t1 + span), step):
        out.append((float(ts), post))
    return out


def self_test():
    """Offline regression test of the verdict math across all tiers and both
    directions. No Prometheus, no containers, no fault injection."""
    t0, t1 = 1000.0, 1100.0
    noise = [0.17, 0.22, 0.19, 0.24, 0.18, 0.21, 0.20, 0.23, 0.16, 0.25]
    inc = {"name": "inc", "canonical": True, "direction": "increase",
           "threshold_sigma": 5, "abs_threshold": 0.8, "min_fraction": 0.8}
    dec = {"name": "dec", "canonical": True, "direction": "decrease",
           "threshold_sigma": 3, "abs_threshold": 0.001, "min_fraction": 0.8}
    bl = {"name": "bl", "canonical": True, "direction": "increase",
          "threshold_sigma": 10, "abs_threshold": 0.25, "min_fraction": 0.7}

    cases = [
        ("step-increase (flat base)", _series(t0, t1, 0.10, 0.95, 0.12), inc, "confirmed"),
        ("flat (no change)",          _series(t0, t1, 0.10, 0.10, 0.10), inc, "unconfirmed"),
        ("decrease-to-zero",          _series(t0, t1, 0.50, 0.00, 0.50), dec, "confirmed"),
        ("noisy-increase",            _noisy_series(t0, t1, noise, 0.90, 0.20), inc, "confirmed"),
        ("borderline (sub-sigma)",    _noisy_series(t0, t1, noise, 0.30, 0.20), bl, "borderline"),
    ]
    ok = True
    for label, samples, tgt, expect in cases:
        c = analyze(samples, t0, t1, 60, 60, tgt)
        got = overall_verdict([c])
        good = got == expect
        ok = ok and good
        print(f"  {'OK ' if good else 'BAD'} {label:<28} -> {got:<12} "
              f"(want {expect}; sigma={c['delta_sigma']} frac={c['fraction_above_threshold']})")

    # Rate-window ramp-up: metric only rises in the 2nd half of the injection
    # window (models a p95 over rate(..[1m]) taking a window to climb). Without
    # settling the fraction gate fails -> unconfirmed; with settle_s the
    # injection stats reflect the settled state -> confirmed. This is the exact
    # case that made a real slow_db run read 'unconfirmed' (frac 0.667 < 0.7).
    ramp = [(float(ts), 0.10) for ts in range(int(t0 - 60), int(t0 + 25), 5)] \
        + [(float(ts), 0.95) for ts in range(int(t0 + 25), int(t1 + 60), 5)]
    c_no = analyze(ramp, t0, t1, 60, 60, inc, settle_s=0)
    c_settle = analyze(ramp, t0, t1, 60, 60, inc, settle_s=30)
    v_no, v_settle = overall_verdict([c_no]), overall_verdict([c_settle])
    ramp_good = (v_no != "confirmed" and v_settle == "confirmed")
    ok = ok and ramp_good
    print(f"  {'OK ' if ramp_good else 'BAD'} {'ramp-up (settle fixes)':<28} -> "
          f"no-settle={v_no} settle={v_settle} (want unconfirmed/borderline -> confirmed)")

    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ground-truth", help="path to a recipe's ground_truth.json")
    ap.add_argument("--targets", default=DEFAULT_TARGETS)
    ap.add_argument("--prometheus", default=os.environ.get("PROMETHEUS", "http://localhost:9090"))
    ap.add_argument("--step", default="5s")
    ap.add_argument("--out", help="verification.json output path")
    ap.add_argument("--plot", help="impact PNG output path (needs matplotlib)")
    ap.add_argument("--self-test", action="store_true", help="offline math check, no network")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())
    if not args.ground_truth:
        ap.error("--ground-truth is required (or use --self-test)")

    with open(args.ground_truth) as f:
        gt = json.load(f)
    with open(args.targets) as f:
        targets_all = json.load(f)

    result = run_verification(gt, targets_all, args.prometheus, args.step, args.out, args.plot)
    print(f"[{result['fault']}] {result['verification_status'].upper()}")
    for c in result["checks"]:
        flag = "*" if c["canonical"] else " "
        print(f" {flag} {c['name']}: {'PASS' if c['passed'] else 'fail'} "
              f"(dir_ok={c['direction_ok']} sigma={c['delta_sigma']} "
              f"frac={c['fraction_above_threshold']} base={c['baseline_mean']} inj={c['injection_mean']})")
    sys.exit(0 if result["verification_status"] != "unconfirmed" else 3)


if __name__ == "__main__":
    main()
