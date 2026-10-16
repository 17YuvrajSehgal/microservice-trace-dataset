#!/usr/bin/env python3
"""Degradation module (RQ1/3/4) — deterministic, seeded, OFFLINE telemetry transforms.

A `DegradedRun` wraps a loaded `Run` and re-implements the modality accessors so every downstream
component (tools → agent/baseline) is oblivious to whether it sees full or thinned telemetry. This
sits BEFORE the reader, so Axis A (telemetry) stays isolated from Axis B (the agent is byte-for-byte
unchanged) — Mahsa's confounding guardrail (research-agentic-rca.md §2).

Knobs (research-agentic-rca.md §5):
  trace_keep      keep this fraction of spans, sampled deterministically by trace_id
  metric_step_s   resample metrics 5s → {10,30,60}s (keep one sample per bucket)
  log_level       drop log lines below ALL | WARN | ERROR
  drop_services   remove ALL telemetry for these services (partial instrumentation)
  drop_modalities drop a whole modality: any of {traces, logs, metrics, kernel} (RQ3)
  kernel_tier     all | L1 | L3 | none  (or a set of critical services via keep_kernel_services)
Every degraded view is reproducible from (run_id, spec, seed).
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field

try:
    import pandas as pd
except ImportError:
    pd = None


@dataclass(frozen=True)
class DegradeSpec:
    trace_keep: float = 1.0
    metric_step_s: int = 0                       # 0 = native (no resample)
    log_level: str = "ALL"                       # ALL | WARN | ERROR
    drop_services: tuple = ()
    drop_modalities: tuple = ()                  # traces|logs|metrics|kernel
    kernel_tier: str = "all"                     # all | L1 | L3 | none
    keep_kernel_services: tuple = ()             # if set, kernel restricted to these ("critical only")
    seed: int = 0

    def key(self) -> str:
        return (f"tk{self.trace_keep}_ms{self.metric_step_s}_lg{self.log_level}"
                f"_ds{'+'.join(self.drop_services) or '-'}_dm{'+'.join(self.drop_modalities) or '-'}"
                f"_kt{self.kernel_tier}_s{self.seed}")


FULL = DegradeSpec()


def _keep_frac_mask(keys, frac, salt):
    """Deterministic keep-mask: hash(key+salt) in [0,1) < frac. Stable per key across runs."""
    if frac >= 1.0:
        return [True] * len(keys)
    out = []
    for k in keys:
        h = int(hashlib.md5(f"{salt}:{k}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        out.append(h < frac)
    return out


class DegradedRun:
    """Same duck-typed interface as stratatrace.Run, but modality methods apply the spec."""

    def __init__(self, base, spec: DegradeSpec):
        self.base = base
        self.spec = spec
        # passthrough attributes the tools read
        self.run_dir = base.run_dir
        self.ground_truth = base.ground_truth
        self.verification = getattr(base, "verification", {})
        self.clock_anchors = getattr(base, "clock_anchors", {})

    # ---- traces ---------------------------------------------------------------------------
    def spans(self):
        if "traces" in self.spec.drop_modalities:
            return _empty()
        df = self.base.spans()
        if not _ok(df):
            return df
        if self.spec.drop_services and "service" in df.columns:
            df = df[~df["service"].isin(self.spec.drop_services)]
        if self.spec.trace_keep < 1.0:
            keycol = "trace_id" if "trace_id" in df.columns else ("span_id" if "span_id" in df.columns else None)
            if keycol is not None:
                keys = df[keycol].astype(str)
                uniq = keys.unique()
                keep = set(u for u, m in zip(uniq, _keep_frac_mask(list(uniq), self.spec.trace_keep,
                                                                    f"{self.run_dir}:trace")) if m)
                df = df[keys.isin(keep)]
        return df

    # ---- logs -----------------------------------------------------------------------------
    def logs(self):
        if "logs" in self.spec.drop_modalities:
            return _empty()
        df = self.base.logs()
        if not _ok(df):
            return df
        if self.spec.drop_services and "container" in df.columns:
            df = df[~df["container"].apply(lambda c: any(s in str(c) for s in self.spec.drop_services))]
        lvl = self.spec.log_level.upper()
        if lvl in ("WARN", "ERROR") and "line" in df.columns:
            keep = {"ERROR": ["ERROR", "FATAL", "SEVERE"],
                    "WARN": ["WARN", "ERROR", "FATAL", "SEVERE"]}[lvl]
            pat = "|".join(keep)
            df = df[df["line"].astype(str).str.contains(pat, case=False, na=False)]
        return df

    # ---- metrics --------------------------------------------------------------------------
    def metrics(self):
        if "metrics" in self.spec.drop_modalities:
            return _empty()
        df = self.base.metrics()
        if not _ok(df) or "timestamp" not in df.columns:
            return df
        if self.spec.drop_services:
            cc = _cont_col(df)
            if cc:
                df = df[~df[cc].apply(lambda c: any(s in str(c) for s in self.spec.drop_services))]
        if self.spec.metric_step_s and self.spec.metric_step_s > 0:
            ts = pd.to_numeric(df["timestamp"], errors="coerce")
            bucket = (ts // self.spec.metric_step_s).astype("Int64")
            keys = ["metric", _cont_col(df)]
            keys = [k for k in keys if k]
            df = df.assign(_b=bucket).drop_duplicates(subset=keys + ["_b"], keep="first").drop(columns="_b")
        return df

    # ---- kernel ---------------------------------------------------------------------------
    def _kernel(self, which):
        if "kernel" in self.spec.drop_modalities or self.spec.kernel_tier == "none":
            return _empty()
        tier = self.spec.kernel_tier
        if tier == "L1" and which != "l1":
            return _empty()
        if tier == "L3" and which != "l3":
            return _empty()
        df = getattr(self.base, {"l1": "kernel_l1", "l2": "kernel_l2", "l3": "kernel_l3"}[which])()
        if not _ok(df):
            return df
        if self.spec.keep_kernel_services and "service" in df.columns:
            df = df[df["service"].isin(self.spec.keep_kernel_services)]
        if self.spec.drop_services and "service" in df.columns:
            df = df[~df["service"].isin(self.spec.drop_services)]
        return df

    def kernel_l1(self):
        return self._kernel("l1")

    def kernel_l2(self):
        return self._kernel("l2")

    def kernel_l3(self):
        return self._kernel("l3")

    def load(self):
        return self.base.load()

    def has_kernel_l0(self):
        return False


def degrade(run, spec: DegradeSpec):
    """Wrap a Run in a degraded view (identity when spec is FULL)."""
    return run if spec == FULL else DegradedRun(run, spec)


def _empty():
    try:
        import pandas as pd
        return pd.DataFrame()
    except ImportError:
        return []


def _ok(df):
    return hasattr(df, "columns") and len(df) > 0


def _cont_col(df):
    return next((c for c in ("container", "name", "container_label_com_docker_compose_service",
                             "pod", "id") if c in df.columns), None)


if __name__ == "__main__":
    # deterministic smoke test: verify each knob reduces the data as expected
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from stratatrace import load_run
    r = load_run(sys.argv[1])
    n0 = (len(r.spans()), len(r.logs()), len(r.metrics()), len(r.kernel_l1()))
    print(f"FULL:              spans={n0[0]} logs={n0[1]} metrics={n0[2]} l1={n0[3]}")
    for spec in [DegradeSpec(trace_keep=0.25), DegradeSpec(metric_step_s=30),
                 DegradeSpec(log_level="ERROR"), DegradeSpec(drop_modalities=("traces",)),
                 DegradeSpec(kernel_tier="L3")]:
        d = DegradedRun(r, spec)
        print(f"{spec.key():40s} spans={len(d.spans())} logs={len(d.logs())} "
              f"metrics={len(d.metrics())} l1={len(d.kernel_l1())} l3={len(d.kernel_l3())}")
