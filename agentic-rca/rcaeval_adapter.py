#!/usr/bin/env python3
"""RCAEval adapter — StrataTrace run → the 4-key dict that Multi-source BARO (`mmbaro`) consumes,
and a diagnose() wrapper that returns our output contract (RCA method #2, non-LLM).

Per the non-llm-baseline.md plan: RCAEval methods ingest pre-aggregated TIME-SERIES, not raw
logs/traces. This adapter's job is that raw→time-series aggregation, on the SAME (possibly degraded)
Run the other methods see — so the method is held fixed and only the data varies (Mahsa's guardrail).
Output dict keys: {metric, logts, tracets_err, tracets_lat}, each a DataFrame with a `time` column.

RCAEval methods LOCALIZE (ranked services), they do not classify fault_type — so we score service
Top-1/Top-3/MRR (= RCAEval's AC@1/AC@3); fault_type is left None for this method.

Runs in the RCAEval venv (/scratch/yuvraj17/.venv-rca, py3.12) which also has stratatrace installed.
"""
from __future__ import annotations
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

_CADV = {  # cadvisor metric -> (short label, is_counter)
    "container_cpu_usage_seconds_total": ("cpu", True),
    "container_memory_working_set_bytes": ("mem", False),
    "container_network_receive_bytes_total": ("netrx", True),
    "container_network_transmit_bytes_total": ("nettx", True),
}


def _svc(name) -> str:
    n = str(name)
    for p in ("docker-compose_", "trainticket_"):
        n = n.replace(p, "")
    return re.sub(r"_\d+$", "", n).strip()


def _to_unix(iso):
    import datetime as dt
    return dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()


def _unix_col(idx):
    """DatetimeIndex → int64 unix SECONDS, robust to pandas-3 variable resolution (s/ms/us/ns)
    and tz-awareness (astype('int64') returns the index's own unit, not always ns)."""
    idx = pd.DatetimeIndex(idx)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.astype("datetime64[ns]").astype("int64") // 10**9


def _metric_frame(run, step):
    m = run.metrics()
    if not hasattr(m, "columns") or len(m) == 0 or "metric" not in m.columns:
        return pd.DataFrame({"time": []})
    cc = next((c for c in ("container", "name", "container_label_com_docker_compose_service", "id")
               if c in m.columns), None)
    if not cc:
        return pd.DataFrame({"time": []})
    m = m[m["metric"].isin(_CADV)].copy()
    m["svc"] = m[cc].map(_svc)
    m["t"] = pd.to_datetime(pd.to_numeric(m["timestamp"], errors="coerce"), unit="s")
    m["v"] = pd.to_numeric(m["value"], errors="coerce")
    cols = []
    for (svc, metric), g in m.groupby(["svc", "metric"]):
        label, counter = _CADV[metric]
        s = g.dropna(subset=["t", "v"]).set_index("t")["v"].sort_index()
        r = (s.resample(f"{step}s").max().diff() / step) if counter else s.resample(f"{step}s").mean()
        cols.append(r.rename(f"{svc}_{label}"))
    if not cols:
        return pd.DataFrame({"time": []})
    df = pd.concat(cols, axis=1)
    # fold kernel L1 syscall-latency peaks in as extra <svc>_kernlat columns (RQ3-inside-mmbaro)
    l1 = run.kernel_l1()
    if hasattr(l1, "columns") and len(l1):
        latc = next((c for c in l1.columns if "p95" in c and "lat" in c), None)
        if latc and "service" in l1.columns and "window_start_s" in l1.columns:
            k = l1[["service", "window_start_s", latc]].copy()
            k["t"] = pd.to_datetime(pd.to_numeric(k["window_start_s"], errors="coerce"), unit="s")
            for svc, g in k.groupby("service"):
                if svc in ("kernel", "system"):
                    continue
                s = g.dropna(subset=["t"]).set_index("t")[latc].sort_index()
                df = df.join(s.resample(f"{step}s").max().rename(f"{_svc(svc)}_kernlat"), how="outer")
    df = df.sort_index()
    df.insert(0, "time", _unix_col(df.index))
    return df.reset_index(drop=True)


def _log_ts(run, step):
    lg = run.logs()
    if not hasattr(lg, "columns") or len(lg) == 0:
        return pd.DataFrame({"time": []})
    ts = pd.to_datetime(lg["line"].astype(str).str.slice(0, 30).str.extract(
        r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)")[0], errors="coerce", utc=True)
    d = pd.DataFrame({"svc": lg["container"].map(_svc), "t": ts}).dropna(subset=["t"])
    if len(d) == 0:
        return pd.DataFrame({"time": []})
    d = d.set_index("t")
    counts = d.groupby("svc").resample(f"{step}s").size().unstack("svc", fill_value=0)
    counts.insert(0, "time", _unix_col(counts.index))
    return counts.reset_index(drop=True)


def _trace_ts(run, step):
    sp = run.spans()
    empty = pd.DataFrame({"time": []})
    if not hasattr(sp, "columns") or len(sp) == 0 or "start_ns" not in sp.columns:
        return empty, empty
    d = sp.copy()
    if "kind" in d.columns:
        d = d[d["kind"].isin([2, "2", "SPAN_KIND_SERVER"])]
    d["t"] = pd.to_datetime(pd.to_numeric(d["start_ns"], errors="coerce"), unit="ns")
    d["svc"] = d["service"].astype(str)
    d = d.dropna(subset=["t"]).set_index("t")
    lat = d.groupby("svc")["dur_ms"].resample(f"{step}s").mean().unstack("svc")
    err_mask = pd.Series(False, index=d.index)
    if "http.response.status_code" in d.columns:
        sc = pd.to_numeric(d["http.response.status_code"], errors="coerce")
        err_mask = err_mask | (sc >= 500).fillna(False)
    if "error.type" in d.columns:
        err_mask = err_mask | d["error.type"].notna()
    d["_err"] = err_mask.astype(int)
    err = d.groupby("svc")["_err"].resample(f"{step}s").sum().unstack("svc")
    for f in (lat, err):
        f.insert(0, "time", _unix_col(f.index))
    return err.reset_index(drop=True), lat.reset_index(drop=True)


def to_rcaeval(run, step_s: int = 5) -> dict:
    err, lat = _trace_ts(run, step_s)
    return {"metric": _metric_frame(run, step_s), "logts": _log_ts(run, step_s),
            "tracets_err": err, "tracets_lat": lat}


def diagnose(run, app: str | None = None, method: str = "mmbaro", **_) -> dict:
    from RCAEval.e2e import mmbaro, baro
    fn = {"mmbaro": mmbaro, "baro": baro}[method]
    gt = run.ground_truth.get("fault", run.ground_truth) or {}
    inject = _to_unix(gt.get("injection_start_utc")) if gt.get("injection_start_utc") else None
    data = to_rcaeval(run) if method == "mmbaro" else _metric_frame(run, 5)
    try:
        out = fn(data, inject)
        ranks = [r for r in out.get("ranks", []) if r != "time"]
        seen, services = set(), []
        for r in ranks:
            s = r.rsplit("_", 1)[0] if "_" in r else r          # <service>_<metric> → service
            if s not in seen:
                seen.add(s); services.append(s)
        top1 = services[0] if services else None
        diagnosis = {"root_cause_service": top1, "fault_type": None,
                     "evidence": f"mmbaro rank1={ranks[0] if ranks else '-'}", "confidence": None}
        return {"run_id": os.path.basename(run.run_dir), "diagnosis": diagnosis,
                "ranked_services": services[:10], "trajectory": [{"tool": method}],
                "n_tool_calls": 4, "bytes_touched": 0, "tokens": {"in": 0, "out": 0},
                "model": f"rcaeval:{method}"}
    except Exception as e:
        return {"run_id": os.path.basename(run.run_dir), "diagnosis": None, "error": repr(e)[:300],
                "ranked_services": [], "trajectory": [], "n_tool_calls": 0,
                "bytes_touched": 0, "tokens": {"in": 0, "out": 0}}


if __name__ == "__main__":
    from stratatrace import load_run
    import json
    rd = sys.argv[1]
    r = load_run(rd)
    d = to_rcaeval(r)
    for k, v in d.items():
        print(f"{k:12s} shape={getattr(v, 'shape', '?')} cols={list(v.columns)[:6] if hasattr(v,'columns') else '-'}")
    out = diagnose(r, app=os.environ.get("STRATATRACE_APP"))
    print("\ndiagnosis:", json.dumps(out.get("diagnosis"), default=str))
    print("ranked:", out.get("ranked_services", [])[:6], "| err:", out.get("error"))
    print("GT target:", r.ground_truth.get("fault", {}).get("target_service"))
