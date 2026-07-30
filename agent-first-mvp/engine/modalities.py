#!/usr/bin/env python3
"""Read the trace/log/metric modalities of a collected run — scoped and byte-counted.

Every reader returns (result, bytes_touched) so phase2 can report how little data the
skill's *scoped* collection spec actually needed vs the undirected everything-bundle
(the collection-aware payoff). All reads are READ-ONLY on ~/traces. Stdlib only.
"""
import gzip, json, os, re, datetime as dt

def _ns_window(begin_iso, end_iso):
    b = dt.datetime.strptime(begin_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    e = dt.datetime.strptime(end_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return int(b.timestamp()*1e9), int(e.timestamp()*1e9)

def _pctl(xs, q):
    if not xs: return None
    xs = sorted(xs); i = min(len(xs)-1, int(q*len(xs)))
    return xs[i]

# ---- traces: per-service SERVER span latency in a window --------------------
def span_latency(spans_path, begin_iso, end_iso, services):
    lo, hi = _ns_window(begin_iso, end_iso)
    want = set(services)
    durs = {s: [] for s in want}
    scoped_bytes = 0
    with open(spans_path, "rb") as f:
        for raw in f:
            # cheap prefilter: only parse lines mentioning a wanted service
            if not any(s.encode() in raw for s in want): continue
            try: obj = json.loads(raw)
            except Exception: continue
            for rs in obj.get("resourceSpans", []):
                svc = None
                for a in rs.get("resource", {}).get("attributes", []):
                    if a.get("key") == "service.name":
                        svc = a.get("value", {}).get("stringValue"); break
                if svc not in want: continue
                matched_here = False
                for ss in rs.get("scopeSpans", []):
                    for sp in ss.get("spans", []):
                        if int(sp.get("kind", 0)) != 2:  # SERVER only
                            continue
                        st = int(sp.get("startTimeUnixNano", 0)); en = int(sp.get("endTimeUnixNano", 0))
                        if st < lo or st > hi: continue
                        durs[svc].append((en - st) / 1e9); matched_here = True
                if matched_here: scoped_bytes += len(raw)
    out = {}
    for s in want:
        d = durs[s]
        out[s] = {"n": len(d), "p50_s": round(_pctl(d,0.5) or 0,4),
                  "p95_s": round(_pctl(d,0.95) or 0,4), "max_s": round(max(d) if d else 0,4)}
    return out, scoped_bytes

# ---- logs: per-request duration + error signatures ---------------------------
_TOOK = re.compile(r"took=([\d.]+)(µs|ms|s|us)\b")
_ERRRE = re.compile(r"(err=(?!null)\S+|\berror\b|\bpanic\b|reset by peer|connection reset|ECONNRESET|"
                    r"connection refused|broken pipe|\btimed?\s*out\b|no such host|dial tcp|\bEOF\b|"
                    r"i/o timeout|[^0-9](5\d\d)[^0-9])", re.I)
_UNIT = {"µs":1e-6, "us":1e-6, "ms":1e-3, "s":1.0}
def _sig(line):  # normalize a log line into a signature: drop digits/hex so variants group
    return re.sub(r"0x[0-9a-f]+|\d+", "N", line)[:110]

def log_signals(logs_dir, services, begin_iso, end_iso):
    lo = dt.datetime.strptime(begin_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    hi = dt.datetime.strptime(end_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    took, errors, bytes_touched = {}, {}, 0
    for svc in services:
        path = os.path.join(logs_dir, f"docker-compose_{svc}_1.log")
        if not os.path.exists(path): continue
        vals, sigcount, sample, nerr = [], {}, {}, 0
        with open(path, "rb") as f:
            for raw in f:
                bytes_touched += len(raw)
                line = raw.decode("utf-8", "replace")
                try: t = dt.datetime.strptime(line[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
                except Exception: t = None
                if t is not None and not (lo <= t <= hi): continue
                mt = _TOOK.search(line)
                if mt: vals.append(float(mt.group(1))*_UNIT.get(mt.group(2),1.0))
                if _ERRRE.search(line):
                    nerr += 1; s = _sig(line.strip()); sigcount[s] = sigcount.get(s,0)+1
                    if s not in sample: sample[s] = line.strip()[-160:]
        if vals:
            took[svc] = {"n": len(vals), "p50_ms": round((_pctl(vals,0.5) or 0)*1e3,2),
                         "p95_ms": round((_pctl(vals,0.95) or 0)*1e3,2), "max_ms": round(max(vals)*1e3,2)}
        if nerr:
            top = sorted(sigcount.items(), key=lambda x:-x[1])[:3]
            errors[svc] = {"n": nerr, "signatures": [{"count": c, "sample": sample[s]} for s, c in top]}
    return {"took": took, "errors": errors}, bytes_touched

# ---- metrics: the pre-computed change-point in verification.json --------------
def metric_changepoint(run_dir):
    path = os.path.join(run_dir, "verification.json")
    if not os.path.exists(path):                      # live captures have no pre-computed check
        return {"status": "live (metric not pre-computed)", "checks": []}, 0
    b = os.path.getsize(path)
    v = json.load(open(path))
    out = []
    for c in v.get("checks", []):
        out.append({"name": c.get("name"), "promql": c.get("promql"),
                    "baseline": c.get("baseline_mean"), "injection": c.get("injection_mean"),
                    "recovery": c.get("recovery_mean"), "delta_sigma": c.get("delta_sigma"),
                    "direction": c.get("direction"), "passed": c.get("passed")})
    return {"status": v.get("verification_status"), "checks": out}, b

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--begin"); ap.add_argument("--end")
    ap.add_argument("--span-services", default="catalogue,front-end")
    ap.add_argument("--log-services", default="catalogue,catalogue-db")
    a = ap.parse_args()
    gt = json.load(open(os.path.join(a.run_dir,"ground_truth.json")))["fault"]
    begin = a.begin or gt["injection_start_utc"]; end = a.end or gt["injection_end_utc"]
    sp, spb = span_latency(os.path.join(a.run_dir,"otlp","spans.jsonl"), begin, end, a.span_services.split(","))
    lg, lgb = log_signals(os.path.join(a.run_dir,"logs"), a.log_services.split(","), begin, end)
    mc, mcb = metric_changepoint(a.run_dir)
    print(json.dumps({"window":[begin,end],
        "spans": sp, "spans_bytes": spb,
        "logs": lg, "logs_bytes": lgb,
        "metrics": mc, "metrics_bytes": mcb}, indent=2))
