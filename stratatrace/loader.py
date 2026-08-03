"""
stratatrace.loader — one-call access to a StrataTrace run's modalities.

    from stratatrace import load_run
    run = load_run("~/traces/anomaly_mem/anomaly_mem_aggressive_steady_r1")
    run.ground_truth          # dict: fault family/name/scope/intensity/window
    run.spans()               # DataFrame: distributed traces (OTLP spans)
    run.logs()                # DataFrame: per-container application logs
    run.metrics()             # DataFrame: Prometheus series (long form)
    run.kernel_l1()           # DataFrame: L1 kernel KPIs (per service, 1s window)
    run.clock_anchors         # dict: (realtime, monotonic, boottime) for cross-modality align

Design goals (msr-research.md §8): one call → time-aligned per-modality dataframes + ground
truth; Parquet for L1–L3, CTF (bt2) for L0, gz-json for metrics. Everything is lazy and
defensive about layout — a run that is missing a modality returns an empty frame, not an error.

NOTE (2026-08-02): exact per-run paths (metrics dir, spans filename) are validated against the
real run layout on the VM next session; the resolvers below try the known candidates and are
easy to pin once confirmed. Kept import-light so it works without the collection stack.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache


def _read_json(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", errors="replace") as fh:
        return json.load(fh)


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _otlp_attrs(attr_list):
    """Flatten an OTLP attributes list [{key, value:{stringValue|intValue|..}}] to a dict."""
    out = {}
    for a in attr_list or []:
        v = a.get("value", {})
        out[a.get("key")] = next(iter(v.values()), None) if isinstance(v, dict) else v
    return out


def _flatten_otlp(obj):
    """Yield one flat row per span from an OTLP export line ({resourceSpans:[...]}).
    If obj is already a flat span (no resourceSpans), yield it unchanged."""
    if not isinstance(obj, dict) or "resourceSpans" not in obj:
        return [obj]
    rows = []
    for rs in obj.get("resourceSpans", []):
        res = _otlp_attrs(rs.get("resource", {}).get("attributes", []))
        service = res.get("service.name")
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                row = {
                    "service": service,
                    "trace_id": sp.get("traceId"),
                    "span_id": sp.get("spanId"),
                    "parent_span_id": sp.get("parentSpanId"),
                    "name": sp.get("name"),
                    "kind": sp.get("kind"),
                    "start_ns": sp.get("startTimeUnixNano"),
                    "end_ns": sp.get("endTimeUnixNano"),
                }
                st, en = sp.get("startTimeUnixNano"), sp.get("endTimeUnixNano")
                try:
                    row["dur_ms"] = (int(en) - int(st)) / 1e6
                except (TypeError, ValueError):
                    row["dur_ms"] = None
                row.update(_otlp_attrs(sp.get("attributes", [])))
                rows.append(row)
    return rows


def _empty_df():
    try:
        import pandas as pd
        return pd.DataFrame()
    except ImportError:
        return []


@dataclass
class Run:
    run_dir: str
    ground_truth: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    clock_anchors: dict = field(default_factory=dict)

    # ---- traces (OTLP spans) -------------------------------------------------------------
    def spans(self):
        """Distributed-trace spans as a DataFrame (one row per span)."""
        path = _first_existing(
            os.path.join(self.run_dir, "otlp", "spans.jsonl"),
            os.path.join(self.run_dir, "otlp-out", "spans.jsonl"),
            *glob.glob(os.path.join(self.run_dir, "otlp", "*.jsonl")),
        )
        if not path:
            return _empty_df()
        spans = []
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                spans.extend(_flatten_otlp(obj))
        try:
            import pandas as pd
            return pd.json_normalize(spans)
        except ImportError:
            return spans

    # ---- logs ----------------------------------------------------------------------------
    def logs(self):
        """Per-container application logs (one row per line: container, ts, message)."""
        rows = []
        for p in glob.glob(os.path.join(self.run_dir, "logs", "*")):
            container = os.path.basename(p).rsplit(".", 1)[0]
            try:
                with open(p, "r", errors="replace") as fh:
                    for line in fh:
                        rows.append({"container": container, "line": line.rstrip("\n")})
            except OSError:
                continue
        try:
            import pandas as pd
            return pd.DataFrame(rows)
        except ImportError:
            return rows

    # ---- metrics (Prometheus, gz per metric) ---------------------------------------------
    def _sibling_dir(self, suffix):
        """Resolve a `<run_id><suffix>` artifact that the collector writes as a SIBLING of the
        run (run_scenario.sh writes metrics to $HOME/<run_id>_metrics, load to
        $HOME/<run_id>_load.csv) — walk up a few parent levels to find it."""
        run_id = os.path.basename(self.run_dir.rstrip("/"))
        p = self.run_dir
        for _ in range(4):
            p = os.path.dirname(p)
            cand = os.path.join(p, run_id + suffix)
            if os.path.exists(cand):
                return cand
        return None

    def metrics(self):
        """Prometheus series in long form (metric, labels, timestamp, value)."""
        mdir = _first_existing(
            os.path.join(self.run_dir, "metrics"),
            os.path.join(self.run_dir, "metrics_full"),
            os.path.join(self.run_dir, "meta", "metrics"),
        ) or self._sibling_dir("_metrics")
        if not mdir:
            return _empty_df()
        rows = []
        for gzf in glob.glob(os.path.join(mdir, "*.json.gz")):
            try:
                blob = _read_json(gzf)
            except (OSError, json.JSONDecodeError):
                continue
            # Prometheus range-query shape: {data:{result:[{metric:{}, values:[[ts,val],..]}]}}
            results = (blob.get("data", {}) or {}).get("result", []) if isinstance(blob, dict) else []
            for series in results:
                labels = series.get("metric", {})
                name = labels.get("__name__", os.path.basename(gzf)[:-8])
                for ts, val in series.get("values", []):
                    rows.append({"metric": name, "timestamp": float(ts),
                                 "value": val, **labels})
        try:
            import pandas as pd
            return pd.DataFrame(rows)
        except ImportError:
            return rows

    # ---- kernel L1 -----------------------------------------------------------------------
    def kernel_l1(self):
        """L1 kernel KPIs (per service, 1s window). Requires the L1 parquet to be derived
        (stratatrace/derive_kernel_l1.py); returns empty if not present."""
        path = _first_existing(
            os.path.join(self.run_dir, "kernel_l1.parquet"),
            os.path.join(self.run_dir, "kernel", "kernel_l1.parquet"),
            os.path.join(self.run_dir, "kernel_l1.csv"),
        )
        if not path:
            return _empty_df()
        try:
            import pandas as pd
            return pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
        except ImportError:
            return []

    def load(self):
        """Closed-loop load-generator results (per-request latency) as a DataFrame.
        Collector writes this as the sibling $HOME/<run_id>_load.csv."""
        path = _first_existing(
            os.path.join(self.run_dir, "load.csv"),
            self._sibling_dir("_load.csv"),
        )
        if not path:
            return _empty_df()
        try:
            import pandas as pd
            return pd.read_csv(path)
        except ImportError:
            return []

    def kernel_l2(self):
        """L2 per-service wait attribution (JSONL from derive_kernel_l2.py); empty if absent."""
        path = _first_existing(os.path.join(self.run_dir, "kernel_l2.jsonl"))
        return self._read_jsonl(path)

    def kernel_l3(self):
        """L3 NL kernel digests (JSONL from derive_kernel_l3.py); empty if absent."""
        path = _first_existing(os.path.join(self.run_dir, "kernel_l3.jsonl"))
        return self._read_jsonl(path)

    @staticmethod
    def _read_jsonl(path):
        if not path:
            return _empty_df()
        rows = []
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        try:
            import pandas as pd
            return pd.DataFrame(rows)
        except ImportError:
            return rows

    def has_kernel_l0(self) -> bool:
        """True if raw CTF channels (L0) are present for this run."""
        return bool(glob.glob(os.path.join(self.run_dir, "kernel", "**", "metadata"), recursive=True))


def load_run(run_dir: str) -> Run:
    """Load a StrataTrace run directory into a lazy multi-modality accessor."""
    run_dir = os.path.abspath(os.path.expanduser(run_dir))
    if not os.path.isdir(run_dir):
        raise FileNotFoundError(run_dir)

    gt = {}
    gt_path = _first_existing(os.path.join(run_dir, "ground_truth.json"))
    if gt_path:
        try:
            gt = _read_json(gt_path)
        except (OSError, json.JSONDecodeError):
            pass

    ver = {}
    v_path = _first_existing(os.path.join(run_dir, "verification.json"))
    if v_path:
        try:
            ver = _read_json(v_path)
        except (OSError, json.JSONDecodeError):
            pass

    # clock anchors for cross-modality alignment (recorded per run in meta/)
    anchors = {}
    for cand in glob.glob(os.path.join(run_dir, "meta", "*")):
        base = os.path.basename(cand).lower()
        if "clock" in base or "anchor" in base or "runinfo" in base:
            try:
                data = _read_json(cand) if cand.endswith((".json", ".gz")) else None
                if isinstance(data, dict):
                    anchors.update({k: v for k, v in data.items()
                                    if any(t in k.lower() for t in ("realtime", "monotonic", "boottime", "clock"))})
            except (OSError, json.JSONDecodeError):
                continue

    return Run(run_dir=run_dir, ground_truth=gt, verification=ver, clock_anchors=anchors)


def list_runs(traces_root: str):
    """Yield (fault_family, run_id, run_dir) for every run under a traces root."""
    traces_root = os.path.abspath(os.path.expanduser(traces_root))
    for fam in sorted(os.listdir(traces_root)):
        fam_dir = os.path.join(traces_root, fam)
        if not os.path.isdir(fam_dir):
            continue
        for run_id in sorted(os.listdir(fam_dir)):
            rd = os.path.join(fam_dir, run_id)
            if os.path.isdir(rd) and os.path.exists(os.path.join(rd, "ground_truth.json")):
                yield fam, run_id, rd
