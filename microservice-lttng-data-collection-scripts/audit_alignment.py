#!/usr/bin/env python3
"""Cross-modality alignment audit for one run bundle (Phase-0 gate tool).

Given a run directory produced by collect_trace.sh (kernel/ ust/ meta/ logs/
otlp/), pick one request trace (explicit --trace-id or the slowest server
span) and show the matching records from every modality side by side:

  1. TRACE   - the OTLP span tree (otlp/spans.jsonl)
  2. LOGS    - docker log lines inside the span window (logs/*.log),
               lines containing the trace_id are starred
  3. LOAD    - client-side rows from the load generator CSV (--load-csv)
  4. METRICS - Prometheus samples bracketing the window (--metrics-dir)
  5. KERNEL  - kernel events inside the window via babeltrace2, attributed
               to containers through the meta/ pid maps (VM only)
  6. CLOCKS  - realtime/monotonic anchor offsets and drift from meta/runinfo

Stdlib only; every section degrades gracefully if its input is missing, so
the tool is usable on partial bundles and on hosts without babeltrace2.

Usage:
  python3 audit_alignment.py <run_dir> [--trace-id HEX] [--load-csv F]
      [--metrics-dir D] [--pad-s 2.0] [--kernel-max-lines 12]
"""

import argparse
import csv
import datetime as dt
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys

UTC = dt.timezone.utc


def ns_to_utc(ns):
    return dt.datetime.fromtimestamp(int(ns) / 1e9, tz=UTC)


def fmt_ts(t):
    return t.strftime("%H:%M:%S.%f") if t else "?"


def parse_docker_ts(s):
    """Parse the RFC3339Nano timestamp docker logs --timestamps prefixes."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z?", s)
    if not m:
        return None
    frac = (m.group(3) or "0")[:6].ljust(6, "0")
    return dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}.{frac}+00:00")


# ---------------------------------------------------------------- spans ----

def load_spans(otlp_file):
    spans = []
    with open(otlp_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                batch = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rs in batch.get("resourceSpans", []):
                svc = "?"
                for a in rs.get("resource", {}).get("attributes", []):
                    if a.get("key") == "service.name":
                        svc = a.get("value", {}).get("stringValue", "?")
                for ss in rs.get("scopeSpans", []):
                    for s in ss.get("spans", []):
                        attrs = {}
                        for a in s.get("attributes", []):
                            v = a.get("value", {})
                            attrs[a.get("key")] = v.get("stringValue", v.get("intValue"))
                        spans.append({
                            "svc": svc,
                            "trace_id": s.get("traceId", ""),
                            "span_id": s.get("spanId", ""),
                            "parent": s.get("parentSpanId", ""),
                            "name": s.get("name", "?"),
                            "kind": int(s.get("kind", 0)),
                            "start_ns": int(s.get("startTimeUnixNano", 0)),
                            "end_ns": int(s.get("endTimeUnixNano", 0)),
                            "attrs": attrs,
                        })
    return spans


# Observability self-traffic: Prometheus scrapes each service's /metrics (and
# health probes hit /health). These produce SERVER spans that are not user
# requests, so they make poor audit anchors - the run's actual load is what we
# want to trace across modalities.
_SELF_TRAFFIC = re.compile(r"/(metrics|health|prometheus)\b", re.IGNORECASE)


def pick_trace(spans, trace_id):
    if trace_id:
        chosen = [s for s in spans if s["trace_id"].lower() == trace_id.lower()]
        if not chosen:
            sys.exit(f"trace_id {trace_id} not found in OTLP file")
        return chosen
    # Slowest server span (kind=2) picks the trace, preferring real user
    # requests over observability self-traffic (/metrics, /health).
    servers = [s for s in spans if s["kind"] == 2]
    user = [s for s in servers if not _SELF_TRAFFIC.search(s["name"])]
    pool = user or servers or spans
    if not pool:
        sys.exit("no spans in OTLP file")
    slowest = max(pool, key=lambda s: s["end_ns"] - s["start_ns"])
    return [s for s in spans if s["trace_id"] == slowest["trace_id"]]


def print_span_tree(trace):
    by_parent = {}
    ids = {s["span_id"] for s in trace}
    roots = []
    for s in trace:
        if s["parent"] and s["parent"] in ids:
            by_parent.setdefault(s["parent"], []).append(s)
        else:
            roots.append(s)

    def walk(span, depth):
        d_ms = (span["end_ns"] - span["start_ns"]) / 1e6
        kind = {1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}.get(span["kind"], "?")
        code = span["attrs"].get("http.status_code", "")
        code = f" status={code}" if code else ""
        print(f"  {'  ' * depth}[{span['svc']}] {span['name']}  ({kind}, "
              f"{fmt_ts(ns_to_utc(span['start_ns']))} +{d_ms:.1f}ms{code})")
        for c in sorted(by_parent.get(span["span_id"], []), key=lambda x: x["start_ns"]):
            walk(c, depth + 1)

    for r in sorted(roots, key=lambda x: x["start_ns"]):
        walk(r, 0)


# ----------------------------------------------------------------- logs ----

def audit_logs(logs_dir, t0, t1, trace_id):
    hits, starred = [], 0
    for path in sorted(glob.glob(os.path.join(logs_dir, "*.log"))):
        svc = os.path.basename(path)[:-4]
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                ts = parse_docker_ts(line)
                if ts is None or not (t0 <= ts <= t1):
                    continue
                star = trace_id and trace_id.lower() in line.lower()
                starred += bool(star)
                hits.append((ts, svc, line.rstrip()[:200], star))
    hits.sort(key=lambda h: h[0])
    return hits, starred


# ----------------------------------------------------------------- load ----

def audit_load_csv(path, t0, t1):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            if not row or row[0].lower().startswith("timestamp"):
                continue
            raw = row[0]
            ts = None
            try:
                ts = dt.datetime.fromtimestamp(float(raw), tz=UTC)
            except ValueError:
                ts = parse_docker_ts(raw)
                if ts is None:
                    try:
                        ts = dt.datetime.fromisoformat(raw).astimezone(UTC)
                    except ValueError:
                        continue
            if t0 <= ts <= t1:
                rows.append((ts, row))
    return rows


# -------------------------------------------------------------- metrics ----

def audit_metrics(metrics_dir, t0, t1, services):
    """Print samples inside [t0, t1] for series relevant to the traced
    services. Handles both export namings: the curated download_metrics.sh
    (files vm_*, <svc>_qps ...) and the full download_metrics_full.sh (files
    named by raw metric name, service identified only in the series labels)."""
    out = []
    svc_set = set(services)
    for path in sorted(glob.glob(os.path.join(metrics_dir, "*.json*"))):
        base = os.path.basename(path).split(".json")[0]
        # Curated naming: filename already encodes host/service relevance.
        name_relevant = base.startswith("vm_") or any(s in base for s in svc_set)
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for series in doc.get("data", {}).get("result", []):
            metric = series.get("metric", {})
            # Raw naming: match the traced services against the label values.
            label_relevant = bool(svc_set) and any(
                s in str(v) for v in metric.values() for s in svc_set)
            if not (name_relevant or label_relevant):
                continue
            vals = [(dt.datetime.fromtimestamp(float(ts), tz=UTC), v)
                    for ts, v in series.get("values", [])]
            inside = [(ts, v) for ts, v in vals if t0 <= ts <= t1]
            if inside:
                label = json.dumps(metric, sort_keys=True)[:90]
                out.append((base, label, inside))
    return out


# --------------------------------------------------------------- kernel ----

def container_tid_map(meta_dir):
    """container -> set(tid) from the docker-top start snapshots."""
    tids = {}
    for path in glob.glob(os.path.join(meta_dir, "top_*_start.txt")):
        name = os.path.basename(path)[len("top_"):-len("_start.txt")]
        with open(path, encoding="utf-8", errors="replace") as f:
            header = f.readline().split()
            try:
                tid_col = [h.upper() for h in header].index("TID")
            except ValueError:
                continue
            for line in f:
                parts = line.split()
                if len(parts) > tid_col and parts[tid_col].isdigit():
                    tids.setdefault(name, set()).add(int(parts[tid_col]))
    return tids


def audit_kernel(kernel_dir, t0, t1, tid_map, max_lines):
    bt = shutil.which("babeltrace2")
    if not bt:
        return None, "babeltrace2 not on PATH - run this on the collection VM"
    # bt2 trimmer: --begin/--end take "YYYY-MM-DD HH:MM:SS.ffffff" and print in
    # the host TZ (the VM is UTC). NOTE: no --clock-gmt - that is a babeltrace
    # v1 flag; passing it to bt2 aborts the run (silent 0 events).
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    cmd = [bt, kernel_dir, "--begin", t0.strftime(fmt), "--end", t1.strftime(fmt)]
    ev_re = re.compile(r"\] \S+ (\S+): \{ cpu_id = \d+ \}, \{ pid = (\d+), tid = (\d+), procname = \"([^\"]*)\"")
    tid_to_container = {t: c for c, ts in (tid_map or {}).items() for t in ts}
    counts, samples, total = {}, [], 0
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        for line in proc.stdout:
            m = ev_re.search(line)
            if not m:
                continue
            total += 1
            event, _pid, tid, procname = m.group(1), m.group(2), int(m.group(3)), m.group(4)
            who = tid_to_container.get(tid, f"host:{procname}")
            counts[(who, event)] = counts.get((who, event), 0) + 1
            if len(samples) < max_lines and tid in tid_to_container:
                samples.append(line.rstrip()[:200])
        stderr = proc.stderr.read()
        proc.wait(timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"babeltrace2 failed: {e}"
    if total == 0:
        # Surface the cause instead of a silent empty result: usually a
        # root-owned CTF (needs the collect_trace.sh chown) or a bt2 error.
        hint = stderr.strip().splitlines()[-1] if stderr.strip() else \
            "0 events in window (check CTF is user-readable and window overlaps the trace)"
        return (0, counts, samples), hint
    return (total, counts, samples), None


# ----------------------------------------------------------------- meta ----

def clock_anchors(meta_dir):
    anchors = {}
    for tag in ("start", "end"):
        path = os.path.join(meta_dir, f"runinfo_{tag}.txt")
        if not os.path.exists(path):
            continue
        vals = {}
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"clock_(realtime|monotonic|boottime)_ns=(\d+)", line.strip())
                if m:
                    vals[m.group(1)] = int(m.group(2))
        if "realtime" in vals and "monotonic" in vals:
            anchors[tag] = vals
    return anchors


# ----------------------------------------------------------------- main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--trace-id", default=None)
    ap.add_argument("--load-csv", default=None)
    ap.add_argument("--metrics-dir", default=None)
    ap.add_argument("--pad-s", type=float, default=2.0)
    ap.add_argument("--kernel-max-lines", type=int, default=12)
    args = ap.parse_args()

    run = args.run_dir
    verdict = {}

    # 1. TRACE
    otlp_file = os.path.join(run, "otlp", "spans.jsonl")
    if not os.path.exists(otlp_file):
        sys.exit(f"missing {otlp_file} - the audit anchors on the trace modality")
    spans = load_spans(otlp_file)
    trace = pick_trace(spans, args.trace_id)
    trace_id = trace[0]["trace_id"]
    t0 = ns_to_utc(min(s["start_ns"] for s in trace)) - dt.timedelta(seconds=args.pad_s)
    t1 = ns_to_utc(max(s["end_ns"] for s in trace)) + dt.timedelta(seconds=args.pad_s)
    services = sorted({s["svc"] for s in trace})

    print("=" * 78)
    print(f"AUDIT trace_id={trace_id}")
    print(f"window {t0.isoformat()} .. {t1.isoformat()}  (pad {args.pad_s}s)")
    print("=" * 78)
    print(f"\n--- 1. TRACE: {len(trace)} span(s), services: {', '.join(services)} ---")
    print_span_tree(trace)
    verdict["trace"] = f"OK ({len(trace)} spans)"

    # 2. LOGS
    logs_dir = os.path.join(run, "logs")
    print(f"\n--- 2. LOGS ({logs_dir}) ---")
    if os.path.isdir(logs_dir):
        hits, starred = audit_logs(logs_dir, t0, t1, trace_id)
        for ts, svc, line, star in hits[:40]:
            print(f"  {'*' if star else ' '} {fmt_ts(ts)} [{svc}] {line}")
        if len(hits) > 40:
            print(f"  ... {len(hits) - 40} more lines in window")
        verdict["logs"] = f"OK ({len(hits)} lines in window, {starred} contain trace_id)" if hits \
            else "EMPTY (no log lines in window)"
    else:
        verdict["logs"] = "MISSING (no logs/ dir)"
        print("  (absent)")

    # 3. LOAD CSV
    print("\n--- 3. LOAD generator ---")
    if args.load_csv and os.path.exists(args.load_csv):
        rows = audit_load_csv(args.load_csv, t0, t1)
        for ts, row in rows[:15]:
            print(f"    {fmt_ts(ts)} {','.join(row[1:7])}")
        verdict["load"] = f"OK ({len(rows)} client requests in window)" if rows else "EMPTY (no rows in window)"
    else:
        verdict["load"] = "SKIPPED (--load-csv not given)"
        print("  (skipped)")

    # 4. METRICS
    print("\n--- 4. METRICS ---")
    if args.metrics_dir and os.path.isdir(args.metrics_dir):
        found = audit_metrics(args.metrics_dir, t0 - dt.timedelta(seconds=30),
                              t1 + dt.timedelta(seconds=30), services)
        for base, label, inside in found[:10]:
            pts = ", ".join(f"{fmt_ts(ts)}={v}" for ts, v in inside[:4])
            print(f"    {base} {label}: {pts}")
        verdict["metrics"] = f"OK ({len(found)} series with samples near window)" if found \
            else "EMPTY (no samples near window)"
    else:
        verdict["metrics"] = "SKIPPED (--metrics-dir not given)"
        print("  (skipped)")

    # 5. KERNEL
    print("\n--- 5. KERNEL ---")
    kernel_dir = os.path.join(run, "kernel", "kernel")
    if os.path.isdir(kernel_dir):
        tid_map = container_tid_map(os.path.join(run, "meta"))
        result, err = audit_kernel(kernel_dir, t0, t1, tid_map, args.kernel_max_lines)
        if err:
            verdict["kernel"] = f"SKIPPED ({err})"
            print(f"  ({err})")
        else:
            total, counts, samples = result
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:12]
            for (who, event), n in top:
                print(f"    {n:>8}  {who:<40} {event}")
            for s in samples:
                print(f"    | {s}")
            verdict["kernel"] = f"OK ({total} events in window, {len(counts)} (container,event) groups)"
    else:
        verdict["kernel"] = "MISSING (no kernel/ dir)"
        print("  (absent)")

    # 6. CLOCKS
    print("\n--- 6. CLOCK anchors (meta/runinfo) ---")
    anchors = clock_anchors(os.path.join(run, "meta"))
    if anchors:
        offs = {}
        for tag, v in anchors.items():
            offs[tag] = v["realtime"] - v["monotonic"]
            print(f"    {tag}: realtime-monotonic offset = {offs[tag]} ns")
        if len(offs) == 2:
            drift = offs["end"] - offs["start"]
            print(f"    offset drift over run = {drift} ns ({drift / 1e6:.3f} ms)")
            verdict["clocks"] = f"OK (drift {drift / 1e6:.3f} ms over run)"
        else:
            verdict["clocks"] = "PARTIAL (only one anchor)"
    else:
        verdict["clocks"] = "MISSING (no clock_* lines in runinfo)"
        print("  (absent)")

    # Verdict
    print("\n" + "=" * 78)
    print("VERDICT")
    for k in ("trace", "logs", "load", "metrics", "kernel", "clocks"):
        print(f"  {k:<8} {verdict[k]}")
    print("=" * 78)


if __name__ == "__main__":
    main()
