#!/usr/bin/env python3
"""Shared Investigation Context (v4) — the typed working memory of one investigation.

The diagram's "Shared Investigation Context": a store of CLAIMS — structured findings
with provenance — that components write and read. Writers today: the Investigation
Context Builder (Phase-1 survey; context_builder.build_context). Readers today: the
skill selector (via digest()) and, when brief injection is enabled, the diagnosis agent
(via format_brief()). Future components (retrieval, skills mining, Issue Analysis)
extend the same store.

A claim:
    {"id": "c0007", "kind": "topology_edge", "subject": "carts-db",
     "predicate": "slow_edge",
     "value": {...tool-shaped numbers...},
     "text": "carts->carts-db p95 3.5->40.6ms (x11.6)",     # one compact line
     "source": {"tool": "topology", "modality": "traces"},   # provenance
     "produced_by": "survey"}

Scope: per-investigation memory (supervisor Q5 — cross-investigation persistence is a
separate, open decision). Claims store RAW names; any model-facing view must be
masked FIRST (leakguard) and only then rendered — see digest()/format_brief() usage in
agent.py.
"""
from __future__ import annotations
import json


class SharedInvestigationContext:
    def __init__(self, run_id: str = ""):
        self.run_id = run_id
        self._claims: list[dict] = []

    # ---- write ---------------------------------------------------------------------------
    def add(self, kind: str, subject: str, predicate: str, value, text: str,
            source: dict | None = None, produced_by: str = "survey") -> str:
        cid = f"c{len(self._claims):04d}"
        self._claims.append({"id": cid, "kind": kind, "subject": subject,
                             "predicate": predicate, "value": value, "text": text,
                             "source": source or {}, "produced_by": produced_by})
        return cid

    # ---- read ----------------------------------------------------------------------------
    def claims(self, kind: str | None = None, subject: str | None = None) -> list[dict]:
        out = self._claims
        if kind:
            out = [c for c in out if c["kind"] == kind]
        if subject:
            out = [c for c in out if c["subject"] == subject]
        return list(out)

    def subjects(self) -> list[str]:
        return sorted({c["subject"] for c in self._claims})

    def __len__(self):
        return len(self._claims)

    def to_jsonable(self) -> dict:
        return {"run_id": self.run_id, "n_claims": len(self._claims), "claims": self._claims}

    # ---- views ---------------------------------------------------------------------------
    def digest(self) -> dict:
        """The compact survey dict (same shape build_survey always produced) — the skill
        selector's input. Mask BEFORE showing to a model: guard.mask_obj(sic.digest())."""
        d = {}
        inv = self.claims(kind="inventory")
        if inv:
            d["services"] = inv[0]["value"].get("services", [])
        edges = [c["value"] for c in self.claims(kind="topology_edge")]
        if edges:
            d["topology_slowest_edges"] = edges
        lat = {c["subject"]: c["value"] for c in self.claims(kind="latency")}
        if lat:
            d["trace_latency_top"] = lat
        logs = {c["subject"]: c["value"] for c in self.claims(kind="log_change")}
        if logs:
            d["log_changes"] = logs
        movers = [c["value"] for c in self.claims(kind="metric_mover")]
        if movers:
            d["metric_top_movers"] = movers
        host = {c["predicate"]: c["value"] for c in self.claims(kind="host_signal")}
        if host:
            d["host"] = host
        kern = {}
        for c in self.claims(kind="kernel_change"):
            kern.setdefault(c["subject"], {})["changed"] = c["value"]
        for c in self.claims(kind="wait_attribution"):
            kern.setdefault(c["subject"], {})["wait_attribution"] = c["value"]
        if kern:
            d["kernel_changes"] = kern
        return d


def format_brief(masked_digest: dict, max_lines_per_section: int = 8) -> str:
    """Render a MASKED digest as the compact investigation brief injected into the
    agent's user message. Pure function over the already-masked dict, so no raw name
    can reach the model through prose."""
    L: list[str] = []

    def sec(title):
        L.append(f"[{title}]")

    d = masked_digest
    if d.get("services"):
        sec("services")
        # masking can collapse several raw names onto one pseudonym — dedupe the view
        seen, svcs = set(), []
        for s in map(str, d["services"]):
            if s not in seen:
                seen.add(s)
                svcs.append(s)
        L.append(", ".join(svcs))
    if d.get("topology_slowest_edges"):
        sec("slow edges (caller->callee, p95 baseline->incident)")
        for e in d["topology_slowest_edges"][:max_lines_per_section]:
            L.append(f"{e.get('caller')}->{e.get('callee')}: "
                     f"{e.get('p95_baseline_ms')}->{e.get('p95_incident_ms')}ms "
                     f"(x{e.get('slowdown_x')}, n={e.get('n_incident')})")
    if d.get("trace_latency_top"):
        sec("server latency (incident window)")
        for svc, v in list(d["trace_latency_top"].items())[:max_lines_per_section]:
            L.append(f"{svc}: p95 {v.get('p95_ms')}ms p99 {v.get('p99_ms')}ms n={v.get('n')}")
    if d.get("log_changes"):
        sec("log error-rate changes (baseline->incident /min)")
        for svc, v in list(d["log_changes"].items())[:max_lines_per_section]:
            if not isinstance(v, dict):
                continue
            line = (f"{svc}: {v.get('err_per_min_baseline')}->{v.get('err_per_min_incident')} "
                    f"(x{v.get('change_x')})")
            new = v.get("new_signatures") or []
            if new:
                line += f"; NEW: {new[0].get('sample', '')[:90]!r}"
            L.append(line)
    if d.get("metric_top_movers"):
        sec("metric movers (baseline->incident)")
        for m in d["metric_top_movers"][:max_lines_per_section]:
            L.append(f"{m.get('container')}: {m.get('signal')} "
                     f"{m.get('baseline')}->{m.get('incident')}")
    if d.get("host"):
        sec("host signals")
        for k, v in d["host"].items():
            if isinstance(v, dict):
                x = f" (x{v.get('change_x')})" if v.get("change_x") is not None else ""
                L.append(f"{k}: {v.get('baseline')}->{v.get('incident')}{x}")
    if d.get("kernel_changes"):
        sec("kernel changes")
        for svc, v in list(d["kernel_changes"].items())[:max_lines_per_section]:
            parts = []
            for ch in (v.get("changed") or [])[:3]:
                parts.append(f"{ch.get('kpi')} {ch.get('baseline')}->{ch.get('incident')} "
                             f"(x{ch.get('x')})")
            wa = v.get("wait_attribution") or {}
            if wa:
                parts.append(f"wait: {json.dumps(wa.get('rule_out_pct'))} "
                             f"hint={wa.get('verdict_hint')}")
            if parts:
                L.append(f"{svc}: " + "; ".join(parts))
    return "\n".join(L)
