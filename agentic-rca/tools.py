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


def _winagg(win, kind):
    """Windowed value of a metric group: gauges -> mean; counters -> per-second rate computed
    PER underlying series (device/interface/cpu/mode label combos) then summed — mixing series
    in one max-min produces garbage rates. groupby(dropna=False): label columns are frame-wide,
    so they are all-NaN for metrics that lack that label, and the default dropna would silently
    drop every row (this zeroed all host counters)."""
    win = win.dropna(subset=["_v", "_ts"])
    if len(win) == 0:
        return None
    if kind == "gauge":
        return float(win["_v"].mean())
    scols = [c for c in ("device", "interface", "cpu", "mode")
             if c in win.columns and win[c].notna().any()]
    tot = 0.0
    groups = win.groupby(scols, dropna=False) if scols else [(None, win)]
    for _, s in groups:
        span = float(s["_ts"].max() - s["_ts"].min())
        if span > 0:
            tot += max(0.0, float((s["_v"].max() - s["_v"].min()) / span))
    return tot


def _norm_container(name: str) -> str:
    """One canonical service name across modalities: metrics say 'docker-compose_carts_1',
    spans/kernel say 'carts' — without this, per-service metric queries silently miss on
    compose-managed containers and cross-tool identity breaks."""
    n = str(name).strip().lstrip("/")
    for pre in ("docker-compose_", "dockercompose_", "compose_", "trainticket_"):
        if n.startswith(pre):
            n = n[len(pre):]
    import re
    return re.sub(r"_\d+$", "", n)


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
    _PSEUDO = {"kernel", "system", "idle", "swapper", "", "none", "nan",
               "prometheus", "cadvisor", "node-exporter", "nodeexporter", "otel-collector", "grafana"}

    def services(self) -> list:
        """Union of service identifiers visible across ALL modalities (spans, kernel, metrics,
        logs), normalized to one name per entity. Metrics/logs-only containers matter: entities
        with no spans (databases, queues, co-tenant workloads) are frequent root causes."""
        svcs = set()
        sp = self._spans()
        if pd is not None and hasattr(sp, "columns") and "service" in getattr(sp, "columns", []):
            svcs |= {_norm_container(s) for s in sp["service"].dropna().unique()}
        l1 = self._l1()
        if hasattr(l1, "columns") and "service" in getattr(l1, "columns", []):
            svcs |= {_norm_container(s) for s in l1["service"].dropna().unique()}
        mt = self._metrics()
        cc = self._metrics_container_col(mt)
        if cc:
            svcs |= {_norm_container(s) for s in mt[cc].dropna().unique()}
        lg = self._logs()
        if hasattr(lg, "columns") and "container" in getattr(lg, "columns", []):
            svcs |= {_norm_container(s) for s in lg["container"].dropna().unique()}
        listed = sorted(s for s in svcs
                        if s and s.lower() not in self._PSEUDO and not s.isdigit())
        return ["host"] + listed            # 'host' = the node itself (node metrics / host-kernel)

    @staticmethod
    def _metrics_container_col(df):
        if not hasattr(df, "columns"):
            return None
        return next((c for c in ("container", "name",
                    "container_label_com_docker_compose_service", "pod", "id") if c in df.columns), None)

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
            out[_norm_container(svc)] = {"n": int(len(g)), "p50_ms": _pctl(dur, 0.5),
                        "p95_ms": _pctl(dur, 0.95), "p99_ms": _pctl(dur, 0.99),
                        "max_ms": round(float(dur.max()), 2) if len(dur.dropna()) else None}
        svc_key = _norm_container(service) if service else None
        return (out.get(svc_key, {"n": 0}) if service else out), _df_bytes(d)

    # ---- topology (victim vs culprit) ----------------------------------------------------
    _PEER_COLS = ("server.address", "network.peer.address", "peer.service")

    def topology(self, service: str | None = None, top: int = 20):
        """Caller→callee edges, baseline vs incident latency per edge. THE victim-vs-culprit
        instrument: victims' slow edges point AT the culprit; the culprit has no slow outgoing
        edge (or none at all). Two edge sources:
          * span parent/child links (both sides emit spans);
          * terminal CLIENT spans → their peer address (callee emits NO spans — databases,
            queues, proxies). Without these, a span-less datastore can never appear as a
            callee and 'edges converge on the datastore' is structurally unobservable.
        Peer-edge callees are flagged spanless_callee=true. Optional service filter."""
        df = self._spans()
        need = {"span_id", "parent_span_id", "service", "start_ns", "dur_ms"}
        if not hasattr(df, "columns") or len(df) == 0 or not need.issubset(set(df.columns)):
            return {"note": "no spans / no parent links"}, 0
        cols = list(need) + [c for c in ("kind", *self._PEER_COLS) if c in df.columns]
        d = df[cols].copy()
        d["service"] = d["service"].map(_norm_container)
        sn = pd.to_numeric(d["start_ns"], errors="coerce")
        d["_inc"] = (sn >= self._ns0) & (sn <= self._ns1) if self._ns0 else False
        d["_base"] = (sn < self._ns0) if self._ns0 else True
        parent_svc = d.set_index("span_id")["service"]
        ch = d[d["parent_span_id"].notna() & (d["parent_span_id"] != "")].copy()
        ch["caller"] = ch["parent_span_id"].map(parent_svc)
        ch = ch[ch["caller"].notna() & (ch["caller"] != ch["service"])]

        def _p95s(g):
            dur = pd.to_numeric(g["dur_ms"], errors="coerce")
            bd, idur = dur[g["_base"]], dur[g["_inc"]]
            if len(idur.dropna()) == 0:
                return None
            pb, pi = _pctl(bd, 0.95), _pctl(idur, 0.95)
            return {"n_incident": int(len(idur)), "p95_baseline_ms": pb, "p95_incident_ms": pi,
                    "slowdown_x": round(pi / pb, 1) if pb and pi else None}

        edges = []
        for (a, b), g in ch.groupby(["caller", "service"]):
            rec = _p95s(g)
            if rec:
                edges.append({"caller": a, "callee": b, **rec})

        # terminal CLIENT spans -> peer edges (callee emits no spans)
        peer_cols = [c for c in self._PEER_COLS if c in d.columns]
        if peer_cols and "kind" in d.columns:
            cl = d[d["kind"].isin([3, "3", "SPAN_KIND_CLIENT"])].copy()
            has_child = set(d.loc[d["parent_span_id"].notna(), "parent_span_id"].unique())
            cl = cl[~cl["span_id"].isin(has_child)]          # no child span -> external call
            peer = None
            for c in peer_cols:
                col = cl[c] if peer is None else peer.fillna(cl[c])
                peer = col
            cl["_peer"] = peer.map(lambda v: _norm_container(v) if isinstance(v, str) and v else None)
            cl = cl[cl["_peer"].notna() & (cl["_peer"] != cl["service"])]
            for (a, b), g in cl.groupby(["service", "_peer"]):
                rec = _p95s(g)
                if rec:
                    edges.append({"caller": a, "callee": b, "spanless_callee": True, **rec})

        if service:
            sk = _norm_container(service)
            edges = [e for e in edges if sk in (e["caller"], e["callee"])]
        edges.sort(key=lambda e: -(e["slowdown_x"] or 0))
        return {"edges": edges[:top]}, _df_bytes(ch)

    # ---- logs ----------------------------------------------------------------------------
    # error pattern (no catastrophic-backtracking alternations); matched vectorized then refined
    _ERR_PAT = (r"err=(?!null)\S+|\berror\b|\bpanic\b|reset by peer|connection reset|ECONNRESET|"
                r"connection refused|broken pipe|timed?\s*out|no such host|exception|\bEOF\b|"
                r"i/o timeout|\b5\d\d\b")

    def logs(self, service: str | None = None, max_sigs: int = 3):
        """Per-container error-rate CHANGE baseline→incident + NEW error signatures. The core RCA
        discipline: chronic noise (signatures equally present before the incident) must not decide
        anything — what matters is what changed at onset. Docker log lines carry an RFC3339Nano
        prefix, which windows every line; unparseable lines are counted separately. Vectorized:
        regex/timestamp parse run once at C-speed (Java stack-trace logs can be huge)."""
        import re
        df = self._logs()
        if not hasattr(df, "columns") or len(df) == 0:
            return {"note": "no logs"}, 0
        d = df.assign(_c=df["container"].map(_norm_container))
        if service:
            d = d[d["_c"] == _norm_container(service)]
        if len(d) == 0:
            return ({"errors": 0} if service else {}), 0
        line = d["line"].astype(str)
        touched = int(line.str.len().sum())
        ts = pd.to_datetime(line.str.slice(0, 35).str.split(" ").str[0],
                            errors="coerce", utc=True)
        try:
            tsec = ts.astype("int64") / 1e9
        except (TypeError, ValueError):
            tsec = pd.Series(float("nan"), index=d.index)
        tsec = tsec.where(ts.notna())
        msg = line.str.replace(r"^\S+\s", "", regex=True).str.slice(0, 400)
        err = msg.str.contains(self._ERR_PAT, case=False, regex=True, na=False)
        base = tsec < self._t0 if self._t0 else pd.Series(False, index=d.index)
        inc = ((tsec >= self._t0) & (tsec <= self._t1)) if self._t0 else pd.Series(True, index=d.index)
        base_min = float(max((self._t0 - tsec[base].min()) / 60.0, 1 / 60)) if base.any() else 1.0
        inc_min = float(max((self._t1 - self._t0) / 60.0, 1 / 60)) if self._t0 else 1.0
        subre = re.compile(r"0x[0-9a-f]+|\d+")

        out = {}
        for cont, g in d[err & (base | inc)].assign(_m=msg[err & (base | inc)],
                                                    _b=base[err & (base | inc)]).groupby("_c"):
            bsig, isig, sample = {}, {}, {}
            for m, is_b in zip(g["_m"], g["_b"]):
                k = subre.sub("N", m)[:110]
                (bsig if is_b else isig)[k] = (bsig if is_b else isig).get(k, 0) + 1
                sample.setdefault(k, m.strip()[-160:])
            eb, ei = sum(bsig.values()), sum(isig.values())
            rb, ri = eb / base_min, ei / inc_min
            new = [(k, c) for k, c in isig.items() if bsig.get(k, 0) == 0]
            new.sort(key=lambda kv: -kv[1])
            chronic = sorted(((k, c) for k, c in isig.items() if bsig.get(k, 0) > 0),
                             key=lambda kv: -kv[1])
            rec = {"err_per_min_baseline": round(rb, 1), "err_per_min_incident": round(ri, 1),
                   "change_x": round(ri / rb, 1) if rb > 0 else ("new" if ri > 0 else None)}
            if new:
                rec["new_signatures"] = [{"count": c, "sample": sample[k]} for k, c in new[:max_sigs]]
            if chronic:
                rec["chronic_top"] = [{"count_incident": c, "count_baseline": bsig[k],
                                       "sample": sample[k]} for k, c in chronic[:1]]
            out[cont] = rec
        unparsed = int(ts.isna().sum())
        if service:
            res = out.get(_norm_container(service), {"errors": 0})
        else:
            # rank: NEW signatures and big rate changes first; cap the container list
            def _key(kv):
                r = kv[1]
                cx = r.get("change_x")
                cxv = 998 if cx == "new" else (cx if isinstance(cx, (int, float)) else 0)
                return (len(r.get("new_signatures", [])), cxv)
            ranked = sorted(out.items(), key=_key, reverse=True)
            res = dict(ranked[:12])
            if len(ranked) > 12:
                res["note"] = f"{len(ranked) - 12} more containers with error activity omitted"
        if unparsed and isinstance(res, dict):
            res.setdefault("untimed_lines", unparsed)
        return res, touched

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

    # host (node-exporter) signals: name -> (kind, label, scale, sum-group label, exclude values)
    _NODE_CURATED = {
        "node_cpu_seconds_total":            ("counter", "host_cpu_busy_cores", 1.0, "mode", ("idle",)),
        "node_disk_io_time_seconds_total":   ("counter", "host_disk_io_time_s/s", 1.0, "device", ()),
        "node_disk_written_bytes_total":     ("counter", "host_disk_write_KB/s", 1e-3, "device", ()),
        "node_disk_read_bytes_total":        ("counter", "host_disk_read_KB/s", 1e-3, "device", ()),
        "node_network_receive_bytes_total":  ("counter", "host_net_rx_KB/s", 1e-3, "device", ("lo",)),
        "node_network_transmit_bytes_total": ("counter", "host_net_tx_KB/s", 1e-3, "device", ("lo",)),
        "node_memory_MemAvailable_bytes":    ("gauge", "host_mem_available_GB", 1e-9, None, ()),
        "node_load1":                        ("gauge", "host_load1", 1.0, None, ()),
    }

    def host_metrics(self):
        """Node-level (whole host) signals baseline→incident — the direct evidence channel for
        host-scoped causes (CPU/disk/memory/network pressure affecting all services at once)."""
        df = self._metrics()
        if not hasattr(df, "columns") or len(df) == 0 or "metric" not in getattr(df, "columns", []):
            return {"note": "no metrics"}, 0
        d = df[df["metric"].isin(self._NODE_CURATED)]
        if len(d) == 0:
            return {"note": "no node-exporter metrics"}, 0
        d = d.assign(_ts=pd.to_numeric(d["timestamp"], errors="coerce"),
                     _v=pd.to_numeric(d["value"], errors="coerce"))
        out = {}
        for met, g in d.groupby("metric"):
            kind, label, sc, grp, excl = self._NODE_CURATED[met]
            if grp and grp in g.columns and excl:
                g = g[~g[grp].astype(str).isin(excl)]
            bv = _winagg(g[g["_ts"] < self._t0], kind) if self._t0 else None
            iv = _winagg(g[(g["_ts"] >= self._t0) & (g["_ts"] <= self._t1)] if self._t0 else g, kind)
            if iv is None:
                continue
            rec = {"baseline": None if bv is None else round(bv * sc, 3),
                   "incident": round(iv * sc, 3)}
            if bv:
                rec["change_x"] = round(iv / bv, 2)
            out[label] = rec
        return (out or {"note": "no node-exporter metrics"}), _df_bytes(d)

    def metrics(self, service: str | None = None, top: int = 8):
        """Per-container resource signals baseline→incident: CPU, throttling, memory, net, fs I/O.
        Counters (*_total) become per-second RATES; gauges use the window mean. Ranked by movement
        relative to each signal's own scale so genuine movers beat near-constant noise.
        service='host' returns node-level host signals instead."""
        if service and _norm_container(service) in ("host", "node"):
            return self.host_metrics()
        df = self._metrics()
        if not hasattr(df, "columns") or len(df) == 0 or "timestamp" not in getattr(df, "columns", []):
            return {"note": "no metrics"}, 0
        cont_col = self._metrics_container_col(df)
        if "metric" not in df.columns or not cont_col:
            return {"note": "metrics lack metric/container columns"}, 0
        d = df.assign(_ts=pd.to_numeric(df["timestamp"], errors="coerce"),
                      _v=pd.to_numeric(df["value"], errors="coerce"))
        d = d[d["metric"].isin(self._CURATED)]
        d = d[d[cont_col].notna() & ~d[cont_col].astype(str).isin(("", "nan", "/"))]
        d = d.assign(**{cont_col: d[cont_col].map(_norm_container)})
        if service:
            d = d[d[cont_col] == _norm_container(service)]

        sigs = []
        for (met, cont), g in d.groupby(["metric", cont_col]):
            kind, label, sc = self._CURATED[met]
            bv = _winagg(g[g["_ts"] < self._t0], kind) if self._t0 else None
            gi = g[(g["_ts"] >= self._t0) & (g["_ts"] <= self._t1)] if self._t0 else g
            iv = _winagg(gi, kind)
            if iv is None:
                continue
            base_for_rel = bv if bv not in (None, 0) else None
            rel = (iv - (bv or 0.0)) / (abs(base_for_rel) if base_for_rel else (abs(iv) or 1))
            # field is named "incident", not "injection": neutral vocabulary for the agent
            # (and "injection" matches leakguard's fault vocab, which would mangle the key)
            sigs.append({"container": cont, "signal": label,
                         "baseline": None if bv is None else round(bv * sc, 3),
                         "incident": round(iv * sc, 3), "rel_change": round(float(rel), 3),
                         "_disp": abs(iv * sc)})
        gmax = {}
        for s in sigs:
            gmax[s["signal"]] = max(gmax.get(s["signal"], 0.0), s["_disp"])
        for s in sigs:
            s["_score"] = abs(s["incident"] - (s["baseline"] or 0)) / (gmax.get(s["signal"], 0.0) + 1e-9)
        sigs.sort(key=lambda x: -x["_score"])
        for s in sigs:
            s.pop("_disp", None); s.pop("_score", None)
        res = {"top_movers": sigs[:top]}
        bt = _df_bytes(d)
        if not service:                     # survey call: include host-level signals up front
            host, hb = self.host_metrics()
            if "note" not in host:
                res["host"] = host
                bt += hb
        return res, bt

    # ---- kernel --------------------------------------------------------------------------
    # L1 KPIs compared baseline→incident: latency percentiles (of the per-second windows) and
    # activity rates. reclaim/writeback/pagefault are the memory-pressure story; block_* the
    # disk story; sched_wakeup contention; net_* the network story.
    _L1_LAT = ("sys_lat_p95_ms", "sys_lat_p99_ms", "blk_lat_p95_ms")
    _L1_RATE = ("sched_wakeup", "block_ops", "block_sectors", "net_events", "net_bytes",
                "reclaim", "writeback", "pagefault", "sys_io", "sys_net", "sys_futex")

    def kernel(self, service: str | None = None, top_changes: int = 5):
        """Kernel evidence per service, baseline→incident: changed L1 KPIs (syscall/block latency,
        disk, net, scheduler, memory-reclaim rates), L3 NL deviations, and L2 wait-attribution
        ('why it waited') when available. The 'kernel' pseudo-service (unattributed kernel threads)
        is reported as 'host-kernel' — host-wide kernel activity no container explains."""
        out = {}
        touched = 0
        want = _norm_container(service) if service else None
        if want in ("host", "node", "kernel"):
            want = "host-kernel"
        l1 = self._l1()
        if hasattr(l1, "columns") and len(l1) and "window_start_s" in l1.columns:
            touched += _df_bytes(l1)
            ws = pd.to_numeric(l1["window_start_s"], errors="coerce")
            rel = ws - float(ws.min())
            inj_s = (self._t1 - self._t0) if (self._t0 and self._t1) else 120.0
            # run protocol: ~60s baseline, then the incident window (same assumption as the alert)
            base_m = rel < 55
            inc_m = (rel >= 60) & (rel <= 60 + inj_s)
            for svc, g in l1.groupby("service"):
                name = "host-kernel" if svc == "kernel" else _norm_container(svc)
                if svc in ("system", "idle", "swapper", ""):
                    continue
                if want and name != want:
                    continue
                gb, gi = g[base_m.loc[g.index]], g[inc_m.loc[g.index]]
                if len(gi) == 0:
                    continue
                changes = []
                for k in self._L1_LAT:
                    if k not in g.columns:
                        continue
                    b = pd.to_numeric(gb[k], errors="coerce").quantile(0.95) if len(gb) else None
                    i = pd.to_numeric(gi[k], errors="coerce").quantile(0.95)
                    if i is None or pd.isna(i) or i < 0.05:
                        continue
                    x = round(float(i) / float(b), 1) if b and not pd.isna(b) and b > 0 else None
                    changes.append({"kpi": k, "baseline": None if b is None or pd.isna(b) else round(float(b), 3),
                                    "incident": round(float(i), 3), "x": x})
                for k in self._L1_RATE:
                    if k not in g.columns:
                        continue
                    b = float(pd.to_numeric(gb[k], errors="coerce").mean()) if len(gb) else 0.0
                    i = float(pd.to_numeric(gi[k], errors="coerce").mean())
                    if pd.isna(i) or i < 1:
                        continue
                    b = 0.0 if pd.isna(b) else b
                    x = round(i / b, 1) if b > 0 else "new"
                    changes.append({"kpi": k + "_per_s", "baseline": round(b, 1),
                                    "incident": round(i, 1), "x": x})

                def _mag(c):
                    x = c.get("x")
                    return 999 if x == "new" else (abs(x - 1) if isinstance(x, (int, float)) else 0)
                changes.sort(key=_mag, reverse=True)
                changes = [c for c in changes if c.get("x") == "new"
                           or (isinstance(c.get("x"), (int, float)) and (c["x"] >= 1.5 or c["x"] <= 0.6))]
                rec = {"windows_incident": int(len(gi))}
                if changes:
                    rec["changed"] = changes[:top_changes]
                out.setdefault(name, {}).update(rec)
        l3 = self._l3()
        if hasattr(l3, "columns") and len(l3) and "deviations" in l3.columns:
            touched += _df_bytes(l3)
            for svc, g in l3.groupby("service"):
                name = "host-kernel" if svc == "kernel" else _norm_container(svc)
                if want and name != want:
                    continue
                devs = [x for x in g["deviations"].tolist() if x]
                if devs:
                    out.setdefault(name, {})["deviations"] = devs[:3]
        l2 = self._l2()
        if hasattr(l2, "columns") and len(l2) and "rule_out_pct" in l2.columns:
            touched += _df_bytes(l2)
            # LEAKAGE GUARD: L2 rows also carry fault_name/fault_target (deriver QC metadata =
            # the ground-truth label). Only the whitelisted, data-derived fields below may ever
            # reach the agent — never widen this to row.to_dict()/full columns.
            for _, row in l2.iterrows():
                name = _norm_container(row.get("service"))
                if want and name != want:
                    continue
                out.setdefault(name, {})["wait_attribution"] = {
                    "rule_out_pct": row.get("rule_out_pct"), "verdict_hint": row.get("verdict_hint")}
        if not out:
            return {"note": "no kernel L1/L2/L3 present"
                    if not want else "service not in kernel data"}, touched
        return (out.get(want, {"note": "service not in kernel data"}) if want else out), touched


# quick manual test:  python tools.py <run_dir>
if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from stratatrace import load_run
    rd = sys.argv[1]
    t = RunTools(load_run(rd), app=os.environ.get("STRATATRACE_APP"))
    print("services:", t.services()[:25])
    for name in ("traces", "topology", "logs", "metrics", "kernel"):
        res, b = getattr(t, name)()
        n = len(res) if isinstance(res, dict) else 0
        print(f"\n== {name}  (bytes_touched≈{b:,}, {n} keys) ==")
        print(json.dumps(res, indent=2, default=str)[:1600])
    res, b = t.metrics("host")
    print(f"\n== metrics(host) ==\n{json.dumps(res, indent=2, default=str)[:800]}")
