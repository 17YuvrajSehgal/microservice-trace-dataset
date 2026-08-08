#!/usr/bin/env python3
"""Four deterministic telemetry tools over a StrataTrace run — the agent's interface.

Each tool answers a scoped query over ONE modality and returns (compact_summary, bytes_touched):
  - compact_summary: small JSON the LLM can reason over (per-service signals), NOT raw rows.
  - bytes_touched:   approximate bytes the tool consumed → the RQ4 cost axis.

Design (research-agentic-rca.md §4): tools read through stratatrace/loader.py so the degradation
module can sit *before* the reader; they work for BOTH apps (service names come from the data, not
hardcoded); and they are deterministic (run + query → fixed answer). The only ground-truth signal a
tool uses is the incident WINDOW (injection_start/end) — treated as "an alert fired at [t0,t1]", the
standard RCA assumption. Tools never reveal the target service or fault type.

A `RunTools` instance caches the loaded frames and exposes:  services(), metrics(), logs(),
traces(), kernel()  — each optionally scoped to one service.
"""
from __future__ import annotations
import os
from functools import lru_cache

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


def _pctl(series, q):
    s = series.dropna() if hasattr(series, "dropna") else series
    if len(s) == 0:
        return None
    return round(float(s.quantile(q)), 4)


def _df_bytes(df) -> int:
    """Approximate bytes a tool 'touched' = in-memory footprint of the rows it read."""
    try:
        return int(df.memory_usage(deep=True).sum())
    except Exception:
        return 0


class RunTools:
    def __init__(self, run, app: str | None = None):
        self.run = run
        self.app = app or os.environ.get("STRATATRACE_APP", "")
        gt = run.ground_truth.get("fault", run.ground_truth) or {}
        self.inj_start = gt.get("injection_start_utc")
        self.inj_end = gt.get("injection_end_utc")
        # unix-second bounds of the incident window (metrics use float unix ts)
        self._t0 = self._to_unix(self.inj_start)
        self._t1 = self._to_unix(self.inj_end)
        # ns bounds (spans use *_ns)
        self._ns0 = int(self._t0 * 1e9) if self._t0 else None
        self._ns1 = int(self._t1 * 1e9) if self._t1 else None

    @staticmethod
    def _to_unix(iso):
        if not iso:
            return None
        import datetime as dt
        return dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()

    # ---- cached frames -------------------------------------------------------------------
    @lru_cache(maxsize=1)
    def _spans(self):
        return self.run.spans()

    @lru_cache(maxsize=1)
    def _logs(self):
        return self.run.logs()

    @lru_cache(maxsize=1)
    def _metrics(self):
        return self.run.metrics()

    @lru_cache(maxsize=1)
    def _l1(self):
        return self.run.kernel_l1()

    @lru_cache(maxsize=1)
    def _l3(self):
        return self.run.kernel_l3()

    @lru_cache(maxsize=1)
    def _l2(self):
        return self.run.kernel_l2()

    # ---- discovery -----------------------------------------------------------------------
    def services(self) -> list:
        """Union of service identifiers visible across modalities (for the agent to explore)."""
        svcs = set()
        sp = self._spans()
        if pd is not None and hasattr(sp, "columns") and "service" in getattr(sp, "columns", []):
            svcs |= set(sp["service"].dropna().unique())
        l1 = self._l1()
        if hasattr(l1, "columns") and "service" in getattr(l1, "columns", []):
            svcs |= set(l1["service"].dropna().unique())
        return sorted(s for s in svcs if s)

    # ---- traces --------------------------------------------------------------------------
    def traces(self, service: str | None = None):
        """Per-service SERVER-span latency in the incident window (p50/p95/p99/count)."""
        df = self._spans()
        if not hasattr(df, "columns") or len(df) == 0:
            return {"note": "no spans"}, 0
        d = df
        # SERVER spans only (kind is 2 or 'SPAN_KIND_SERVER' depending on exporter)
        if "kind" in d.columns:
            d = d[d["kind"].isin([2, "2", "SPAN_KIND_SERVER"])]
        if self._ns0 and "start_ns" in d.columns:
            sn = pd.to_numeric(d["start_ns"], errors="coerce")
            d = d[(sn >= self._ns0) & (sn <= self._ns1)]
        if service:
            d = d[d["service"] == service]
        out = {}
        for svc, g in d.groupby("service"):
            dur = pd.to_numeric(g.get("dur_ms"), errors="coerce")
            out[svc] = {"n": int(len(g)), "p50_ms": _pctl(dur, 0.5),
                        "p95_ms": _pctl(dur, 0.95), "p99_ms": _pctl(dur, 0.99),
                        "max_ms": round(float(dur.max()), 2) if len(dur.dropna()) else None}
        return (out.get(service, {"n": 0}) if service else out), _df_bytes(d)

    # ---- logs ----------------------------------------------------------------------------
    def logs(self, service: str | None = None, max_sigs: int = 3):
        """Per-container error counts + top normalized error signatures in the run."""
        import re
        df = self._logs()
        if not hasattr(df, "columns") or len(df) == 0:
            return {"note": "no logs"}, 0
        errre = re.compile(r"(err=(?!null)\S+|\berror\b|\bpanic\b|reset by peer|connection reset|"
                           r"ECONNRESET|connection refused|broken pipe|\btimed?\s*out\b|no such host|"
                           r"exception|\bEOF\b|i/o timeout|[^0-9](5\d\d)[^0-9])", re.I)
        sig = lambda s: re.sub(r"0x[0-9a-f]+|\d+", "N", s)[:110]
        d = df[df["container"] == service] if service else df
        out, touched = {}, 0
        for cont, g in d.groupby("container"):
            counts, sample, nerr = {}, {}, 0
            for line in g["line"]:
                touched += len(line) + 1
                if errre.search(line):
                    nerr += 1; k = sig(line)
                    counts[k] = counts.get(k, 0) + 1
                    sample.setdefault(k, line.strip()[-160:])
            if nerr:
                top = sorted(counts.items(), key=lambda x: -x[1])[:max_sigs]
                out[cont] = {"errors": nerr,
                             "top": [{"count": c, "sample": sample[k]} for k, c in top]}
        return (out.get(service, {"errors": 0}) if service else out), touched

    # ---- metrics -------------------------------------------------------------------------
    def metrics(self, service: str | None = None, top: int = 6):
        """Per-container resource metrics: baseline→injection mean shift (which containers moved)."""
        df = self._metrics()
        if not hasattr(df, "columns") or len(df) == 0 or "timestamp" not in getattr(df, "columns", []):
            return {"note": "no metrics"}, 0
        ts = pd.to_numeric(df["timestamp"], errors="coerce")
        val = pd.to_numeric(df["value"], errors="coerce")
        cont_col = next((c for c in ("container", "name", "container_label_com_docker_compose_service",
                                     "pod", "id") if c in df.columns), None)
        d = df.assign(_ts=ts, _v=val)
        base = d[d["_ts"] < self._t0] if self._t0 else d.iloc[0:0]
        inj = d[(d["_ts"] >= self._t0) & (d["_ts"] <= self._t1)] if self._t0 else d
        movers = []
        keycols = [c for c in ("metric", cont_col) if c]
        if keycols:
            bmean = base.groupby(keycols)["_v"].mean()
            imean = inj.groupby(keycols)["_v"].mean()
            for key in imean.index:
                b = bmean.get(key, float("nan")); i = imean.get(key)
                if pd.isna(i):
                    continue
                delta = (i - b) if not pd.isna(b) else i
                denom = abs(b) if (not pd.isna(b) and abs(b) > 1e-9) else (abs(i) or 1)
                rel = delta / denom
                metric = key[0] if isinstance(key, tuple) else key
                cont = key[1] if (isinstance(key, tuple) and len(key) > 1) else None
                if service and cont != service:
                    continue
                movers.append({"metric": metric, "container": cont,
                               "baseline": round(float(b), 4) if not pd.isna(b) else None,
                               "injection": round(float(i), 4), "rel_change": round(float(rel), 3)})
        movers.sort(key=lambda m: -abs(m["rel_change"]))
        return {"top_movers": movers[:top]}, _df_bytes(d)

    # ---- kernel --------------------------------------------------------------------------
    def kernel(self, service: str | None = None):
        """Kernel evidence per service: L1 syscall-latency peaks, L3 NL digest/deviations, and
        L2 wait-attribution rule-out % when available (the 'why it waited' signal)."""
        out = {}
        touched = 0
        l1 = self._l1()
        if hasattr(l1, "columns") and len(l1):
            touched += _df_bytes(l1)
            d = l1[l1["service"] == service] if service else l1
            latcol = next((c for c in l1.columns if "p95" in c and "lat" in c), None)
            for svc, g in d.groupby("service"):
                rec = {"windows": int(len(g))}
                if latcol:
                    rec["sys_lat_p95_ms_peak"] = round(float(pd.to_numeric(g[latcol], errors="coerce").max()), 2)
                out.setdefault(svc, {}).update(rec)
        l3 = self._l3()
        if hasattr(l3, "columns") and len(l3) and "deviations" in l3.columns:
            touched += _df_bytes(l3)
            d = l3[l3["service"] == service] if service else l3
            for svc, g in d.groupby("service"):
                devs = [x for x in g["deviations"].tolist() if x]
                if devs:
                    out.setdefault(svc, {})["deviations"] = devs[:3]
        l2 = self._l2()
        if hasattr(l2, "columns") and len(l2) and "rule_out_pct" in l2.columns:
            touched += _df_bytes(l2)
            d = l2[l2["service"] == service] if service else l2
            for _, row in d.iterrows():
                svc = row.get("service")
                out.setdefault(svc, {})["wait_attribution"] = {
                    "rule_out_pct": row.get("rule_out_pct"), "verdict_hint": row.get("verdict_hint")}
        if not out:
            return {"note": "no kernel L1/L2/L3 present"}, touched
        return (out.get(service, {"note": "service not in kernel data"}) if service else out), touched


# quick manual test:  python tools.py <run_dir>
if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from stratatrace import load_run
    rd = sys.argv[1]
    t = RunTools(load_run(rd), app=os.environ.get("STRATATRACE_APP"))
    print("services:", t.services()[:20])
    for name in ("traces", "logs", "metrics", "kernel"):
        res, b = getattr(t, name)()
        n = len(res) if isinstance(res, dict) else 0
        print(f"\n== {name}  (bytes_touched≈{b:,}, {n} services) ==")
        print(json.dumps(res, indent=2, default=str)[:1200])
