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
        pseudo = {"kernel", "system", "idle", "swapper", ""}
        return sorted(s for s in svcs if s and s not in pseudo)

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
    # error pattern (no catastrophic-backtracking alternations); matched vectorized then refined
    _ERR_PAT = (r"err=(?!null)\S+|\berror\b|\bpanic\b|reset by peer|connection reset|ECONNRESET|"
                r"connection refused|broken pipe|timed?\s*out|no such host|exception|\bEOF\b|"
                r"i/o timeout|\b5\d\d\b")

    def logs(self, service: str | None = None, max_sigs: int = 3):
        """Per-container error counts + top normalized error signatures. Vectorized: the regex runs
        once at C-speed over (length-capped) lines; only the matched lines are grouped in Python —
        Java stack-trace logs can be GBs, so a per-line Python loop is untenable."""
        import re
        df = self._logs()
        if not hasattr(df, "columns") or len(df) == 0:
            return {"note": "no logs"}, 0
        d = df[df["container"] == service] if service else df
        line = d["line"].astype(str).str.slice(0, 500)     # cap length (speed + anti-backtracking)
        touched = int(line.str.len().sum())
        mask = line.str.contains(self._ERR_PAT, case=False, regex=True, na=False)
        if not mask.any():
            return ({"errors": 0} if service else {}), touched
        err = d.loc[mask].assign(_l=line[mask].values)
        subre = re.compile(r"0x[0-9a-f]+|\d+")
        out = {}
        for cont, g in err.groupby("container"):
            counts, sample = {}, {}
            for l in g["_l"]:
                k = subre.sub("N", l)[:110]
                counts[k] = counts.get(k, 0) + 1
                sample.setdefault(k, l.strip()[-160:])
            top = sorted(counts.items(), key=lambda x: -x[1])[:max_sigs]
            out[cont] = {"errors": int(len(g)),
                         "top": [{"count": c, "sample": sample[k]} for k, c in top]}
        return (out.get(service, {"errors": 0}) if service else out), touched

    # ---- metrics -------------------------------------------------------------------------
    # curated cAdvisor signals: counters (*_total) → per-second RATE; gauges → window mean; display scale
    _CURATED = {
        "container_cpu_usage_seconds_total":          ("counter", "cpu_cores", 1.0),
        "container_cpu_cfs_throttled_seconds_total":  ("counter", "cpu_throttled_s/s", 1.0),
        "container_memory_working_set_bytes":         ("gauge",   "mem_working_MB", 1e-6),
        "container_memory_rss":                       ("gauge",   "mem_rss_MB", 1e-6),
        "container_network_receive_bytes_total":      ("counter", "net_rx_KB/s", 1e-3),
        "container_network_transmit_bytes_total":     ("counter", "net_tx_KB/s", 1e-3),
        "container_fs_reads_bytes_total":             ("counter", "fs_read_KB/s", 1e-3),
        "container_fs_writes_bytes_total":            ("counter", "fs_write_KB/s", 1e-3),
    }

    def metrics(self, service: str | None = None, top: int = 8):
        """Per-container resource signals baseline→injection: CPU, throttling, memory, net, fs I/O.
        Counters (*_total) become per-second RATES; gauges use the window mean. Ranked by movement
        relative to each signal's own scale so genuine movers beat near-constant noise."""
        df = self._metrics()
        if not hasattr(df, "columns") or len(df) == 0 or "timestamp" not in getattr(df, "columns", []):
            return {"note": "no metrics"}, 0
        cont_col = next((c for c in ("container", "name",
                        "container_label_com_docker_compose_service", "pod", "id") if c in df.columns), None)
        if "metric" not in df.columns or not cont_col:
            return {"note": "metrics lack metric/container columns"}, 0
        d = df.assign(_ts=pd.to_numeric(df["timestamp"], errors="coerce"),
                      _v=pd.to_numeric(df["value"], errors="coerce"))
        d = d[d["metric"].isin(self._CURATED)]
        if service:
            d = d[d[cont_col] == service]

        def winval(g, kind):
            g = g.dropna(subset=["_v", "_ts"])
            if len(g) == 0:
                return None
            if kind == "gauge":
                return float(g["_v"].mean())
            span = float(g["_ts"].max() - g["_ts"].min())
            return max(0.0, float((g["_v"].max() - g["_v"].min()) / span)) if span > 0 else 0.0

        sigs = []
        for (met, cont), g in d.groupby(["metric", cont_col]):
            kind, label, sc = self._CURATED[met]
            bv = winval(g[g["_ts"] < self._t0], kind) if self._t0 else None
            gi = g[(g["_ts"] >= self._t0) & (g["_ts"] <= self._t1)] if self._t0 else g
            iv = winval(gi, kind)
            if iv is None:
                continue
            base_for_rel = bv if bv not in (None, 0) else None
            rel = (iv - (bv or 0.0)) / (abs(base_for_rel) if base_for_rel else (abs(iv) or 1))
            sigs.append({"container": cont, "signal": label,
                         "baseline": None if bv is None else round(bv * sc, 3),
                         "injection": round(iv * sc, 3), "rel_change": round(float(rel), 3),
                         "_disp": abs(iv * sc)})
        gmax = {}
        for s in sigs:
            gmax[s["signal"]] = max(gmax.get(s["signal"], 0.0), s["_disp"])
        for s in sigs:
            s["_score"] = abs(s["injection"] - (s["baseline"] or 0)) / (gmax.get(s["signal"], 0.0) + 1e-9)
        sigs.sort(key=lambda x: -x["_score"])
        for s in sigs:
            s.pop("_disp", None); s.pop("_score", None)
        return {"top_movers": sigs[:top]}, _df_bytes(d)

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
            # LEAKAGE GUARD: L2 rows also carry fault_name/fault_target (deriver QC metadata =
            # the ground-truth label). Only the whitelisted, data-derived fields below may ever
            # reach the agent — never widen this to row.to_dict()/full columns.
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
