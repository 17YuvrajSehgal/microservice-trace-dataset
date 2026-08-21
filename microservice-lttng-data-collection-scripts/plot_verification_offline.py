#!/usr/bin/env python3
"""Regenerate a run's verification.png from ARCHIVED metrics (no live Prometheus).

`verify_injection.py` produces the impact plot at collection time by querying a running
Prometheus. Train Ticket runs were verified without that step, so they carry a complete
verification.json but no picture. This script rebuilds the picture afterwards by
evaluating the same PromQL against the run's own `metrics/*.json.gz`.

It implements only the query shapes the fault catalog actually uses:

    rate(NAME{sel}[Xm])            increase(NAME{sel}[Xm])
    avg|min|max|sum(EXPR)          NAME{sel} / NAME{sel}
    100 - (EXPR * 100)             NAME{sel}

Selectors support one or more `label="v"` / `label=~"re"` matchers.

    python3 plot_verification_offline.py <run_dir> [--force] [--check]

--check recomputes the stored baseline/injection means instead of plotting, so the
evaluator can be validated against runs whose numbers were produced by real Prometheus.
"""
from __future__ import annotations

import argparse, datetime as dt, glob, gzip, json, os, re, sys

UTC = dt.timezone.utc
UNIT_S = {"s": 1, "m": 60, "h": 3600}


# ------------------------------------------------------------------ loading --

def load_metric(metrics_dir, name):
    """[(labels, [(ts, float)]), ...] for one metric name, from <name>.json.gz."""
    path = os.path.join(metrics_dir, name + ".json.gz")
    if not os.path.exists(path):
        return []
    try:
        blob = json.load(gzip.open(path, "rt"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for s in (blob.get("data", {}) or {}).get("result", []):
        vals = []
        for ts, v in s.get("values", []):
            try:
                vals.append((float(ts), float(v)))
            except (TypeError, ValueError):
                pass
        if vals:
            out.append((s.get("metric", {}), vals))
    return out


def match(labels, matchers):
    for k, op, want in matchers:
        got = labels.get(k, "")
        if op == "=" and got != want:
            return False
        if op == "!=" and got == want:
            return False
        if op == "=~" and not re.fullmatch(want, got):
            return False
        if op == "!~" and re.fullmatch(want, got):
            return False
    return True


SEL_RE = re.compile(r'^([A-Za-z_:][A-Za-z0-9_:]*)\s*(?:\{(.*)\})?$', re.S)
MATCH_RE = re.compile(r'(\w+)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"')


def select(metrics_dir, expr):
    m = SEL_RE.match(expr.strip())
    if not m:
        raise ValueError(f"not a selector: {expr!r}")
    name, body = m.group(1), m.group(2) or ""
    matchers = [(k, op, v.replace('\\"', '"')) for k, op, v in MATCH_RE.findall(body)]
    return [(lb, vs) for lb, vs in load_metric(metrics_dir, name) if match(lb, matchers)]


# --------------------------------------------------------------- evaluation --

def _rate(vals, window, as_increase=False):
    """Prometheus-like rate()/increase(): counter-reset aware, evaluated at each sample."""
    out = []
    for i, (t, _) in enumerate(vals):
        win = [(ts, v) for ts, v in vals[:i + 1] if ts > t - window]
        if len(win) < 2:
            continue
        delta = 0.0
        for j in range(1, len(win)):
            d = win[j][1] - win[j - 1][1]
            delta += d if d >= 0 else win[j][1]      # reset -> count from zero
        span = win[-1][0] - win[0][0]
        if span <= 0:
            continue
        out.append((t, delta if as_increase else delta / span))
    return out


def _align(series_list, fn):
    """Combine several [(ts,v)] on shared timestamps with fn(list_of_v)."""
    if not series_list:
        return []
    common = set(t for t, _ in series_list[0])
    for s in series_list[1:]:
        common &= set(t for t, _ in s)
    maps = [dict(s) for s in series_list]
    return [(t, fn([m[t] for m in maps])) for t in sorted(common)]


def _split_top(expr, ops):
    """Split on a top-level binary operator (ignores anything inside (), {}, [], "")."""
    depth = quote = 0
    for i, ch in enumerate(expr):
        if ch == '"':
            quote ^= 1
        if quote:
            continue
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        elif depth == 0:
            for op in ops:
                if expr.startswith(op, i):
                    # not a unary minus, and not part of "=~"
                    if op == "-" and (i == 0 or expr[i - 1] in "(*/+-,"):
                        continue
                    return expr[:i].strip(), op, expr[i + len(op):].strip()
    return None


def _strip_parens(expr):
    """Drop a fully-enclosing pair of parentheses, repeatedly. '(a)*(b)' is left alone."""
    while expr.startswith("(") and expr.endswith(")"):
        depth = quote = 0
        encloses = True
        for i, ch in enumerate(expr):
            if ch == '"':
                quote ^= 1
            if quote:
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i < len(expr) - 1:
                    encloses = False
                    break
        if not (encloses and depth == 0):
            break
        expr = expr[1:-1].strip()
    return expr


def evaluate(expr, metrics_dir):
    """PromQL subset -> [(ts, value)] (a single series)."""
    expr = _strip_parens(expr.strip())

    for ops in (("+", "-"), ("*", "/")):
        sp = _split_top(expr, ops)
        if sp:
            lhs, op, rhs = sp
            f = {"+": lambda a, b: a + b, "-": lambda a, b: a - b,
                 "*": lambda a, b: a * b, "/": lambda a, b: a / b if b else 0.0}[op]
            try:                                   # scalar on the left  (100 - X)
                k = float(lhs)
                return [(t, f(k, v)) for t, v in evaluate(rhs, metrics_dir)]
            except ValueError:
                pass
            try:                                   # scalar on the right (X * 100)
                k = float(rhs)
                return [(t, f(v, k)) for t, v in evaluate(lhs, metrics_dir)]
            except ValueError:
                pass
            a, b = evaluate(lhs, metrics_dir), evaluate(rhs, metrics_dir)
            return _align([a, b], lambda vs: f(vs[0], vs[1]))

    m = re.match(r'^(avg|min|max|sum)\s*\((.*)\)$', expr, re.S)
    if m:
        agg, inner = m.group(1), m.group(2)
        fn = {"avg": lambda vs: sum(vs) / len(vs), "min": min, "max": max, "sum": sum}[agg]
        parts = _series_list(inner, metrics_dir)
        return _align(parts, fn) if parts else []

    m = re.match(r'^(rate|increase)\s*\((.*)\[(\d+)([smh])\]\s*\)$', expr, re.S)
    if m:
        fname, inner, num, unit = m.groups()
        window = int(num) * UNIT_S[unit]
        parts = [_rate(vs, window, fname == "increase") for _, vs in select(metrics_dir, inner)]
        parts = [p for p in parts if p]
        if not parts:
            return []
        return parts[0] if len(parts) == 1 else _align(parts, sum)

    parts = [vs for _, vs in select(metrics_dir, expr)]
    if not parts:
        return []
    return parts[0] if len(parts) == 1 else _align(parts, sum)


def _series_list(expr, metrics_dir):
    """Inside an aggregation: keep the per-series split rather than pre-summing."""
    expr = expr.strip()
    m = re.match(r'^(rate|increase)\s*\((.*)\[(\d+)([smh])\]\s*\)$', expr, re.S)
    if m:
        fname, inner, num, unit = m.groups()
        w = int(num) * UNIT_S[unit]
        return [p for p in (_rate(vs, w, fname == "increase") for _, vs in select(metrics_dir, inner)) if p]
    try:
        return [vs for _, vs in select(metrics_dir, expr)]
    except ValueError:
        s = evaluate(expr, metrics_dir)
        return [s] if s else []


# ------------------------------------------------------------------ plotting --

def plot(out_png, series_by_name, t_start, t_end, warmup_s=0):
    """Same look as verify_injection.try_plot, plus an honesty marker.

    `warmup_s` greys the leading region where rate() had less than a full lookback
    window of archived history — those points read high and are not comparable to a
    plot drawn from a live Prometheus.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(len(series_by_name), 1, sharex=True,
                             figsize=(9, 2.4 * len(series_by_name)), squeeze=False)
    for ax, (name, samples) in zip(axes[:, 0], series_by_name.items()):
        ax.plot([dt.datetime.fromtimestamp(ts, UTC) for ts, _ in samples],
                [v for _, v in samples], lw=1.2)
        ax.axvspan(dt.datetime.fromtimestamp(t_start, UTC),
                   dt.datetime.fromtimestamp(t_end, UTC), alpha=0.15, color="red")
        if warmup_s and samples:
            t0 = samples[0][0]
            ax.axvspan(dt.datetime.fromtimestamp(t0, UTC),
                       dt.datetime.fromtimestamp(t0 + warmup_s, UTC), alpha=0.10, color="grey")
        ax.set_ylabel(name, fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    axes[-1, 0].set_xlabel("time (injection window shaded red)")
    fig.text(0.005, 0.005,
             "Redrawn from this run's archived metrics, not from a live Prometheus. "
             f"Grey = first {int(warmup_s)}s, where the rate window is only partly filled and reads high.",
             fontsize=6, color="0.35")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(out_png, dpi=90)
    plt.close(fig)
    return out_png


# ---------------------------------------------------------------------- main --

def parse_utc(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def find_metrics_dir(run_dir):
    inside = os.path.join(run_dir, "metrics")
    if os.path.isdir(inside):
        return inside
    run = os.path.basename(run_dir.rstrip("/"))
    p = run_dir
    for _ in range(4):                                    # legacy sibling layout
        p = os.path.dirname(p)
        cand = os.path.join(p, run + "_metrics")
        if os.path.isdir(cand):
            return cand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--force", action="store_true", help="overwrite an existing verification.png")
    ap.add_argument("--check", action="store_true",
                    help="recompute stored means instead of plotting (validates the evaluator)")
    a = ap.parse_args()

    rd = a.run_dir.rstrip("/")
    run = os.path.basename(rd)
    vj = os.path.join(rd, "verification.json")
    if not os.path.exists(vj):
        print(f"SKIP {run}: no verification.json"); return 0
    out_png = os.path.join(rd, "verification.png")
    if os.path.exists(out_png) and not (a.force or a.check):
        print(f"SKIP {run}: verification.png exists"); return 0

    v = json.load(open(vj))
    md = find_metrics_dir(rd)
    if not md:
        print(f"SKIP {run}: no metrics directory"); return 1

    win = v.get("injection_window_utc") or []
    if len(win) != 2:
        print(f"SKIP {run}: no injection window"); return 1
    t0, t1 = parse_utc(win[0]).timestamp(), parse_utc(win[1]).timestamp()

    series, problems = {}, []
    for c in v.get("checks", []):
        q = c.get("promql", "")
        try:
            s = evaluate(q, md)
        except Exception as e:                                        # noqa: BLE001
            problems.append(f"{c.get('name')}: {type(e).__name__}: {e}"); continue
        if not s:
            problems.append(f"{c.get('name')}: no data for {q}"); continue
        series[c.get("name", "check")] = s

        if a.check:
            base = [val for ts, val in s if ts < t0]
            inj = [val for ts, val in s if t0 <= ts <= t1]
            bm = sum(base) / len(base) if base else float("nan")
            im = sum(inj) / len(inj) if inj else float("nan")
            sb, si = c.get("baseline_mean"), c.get("injection_mean")
            def rel(x, y):
                if y in (None, 0) or x != x: return float("inf")
                return abs(x - y) / abs(y)
            print(f"  {c.get('name'):32s} baseline {bm:12.4f} (stored {sb:12.4f}, off {rel(bm,sb)*100:5.1f}%)"
                  f" | injection {im:12.4f} (stored {si:12.4f}, off {rel(im,si)*100:5.1f}%)")

    if a.check:
        for p in problems: print("  PROBLEM", p)
        return 0
    if not series:
        print(f"FAIL {run}: no series evaluated" + (f" ({problems[0]})" if problems else "")); return 1

    warmup = max([int(n) * UNIT_S[u]
                  for n, u in re.findall(r'\[(\d+)([smh])\]', json.dumps(v.get("checks", [])))] or [0])
    plot(out_png, series, t0, t1, warmup_s=warmup)
    # stored means stay exactly as real Prometheus computed them — only record the picture
    v["impact_plot"] = out_png
    v["impact_plot_source"] = "regenerated offline from archived metrics (plot_verification_offline.py)"
    json.dump(v, open(vj, "w"), indent=2)
    extra = f"  (skipped: {len(problems)})" if problems else ""
    print(f"OK   {run}: {len(series)} check(s) plotted{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
