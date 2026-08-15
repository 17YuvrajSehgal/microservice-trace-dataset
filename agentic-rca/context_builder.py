#!/usr/bin/env python3
"""Investigation Context Builder (v4, Phase 1) — deterministic evidence survey.

Runs the same no-filter queries the agent's SURVEY step would run and distills a compact
evidence digest: what changed baseline→incident across topology, traces, logs, metrics
(incl. host) and kernel. No LLM, no ground truth — pure tool output.

Current consumer: the skill selector (skillreg.select) routes on this digest (masked).
The Phase-2 diagnosis agent deliberately does NOT receive it yet, so the v3 skills-off
condition stays byte-identical to the frozen v3 method and the skill effect is the only
variable (new_design.md §5.1). Injecting the brief into the agent is a separate,
separately-measured toggle later.
"""
from __future__ import annotations


def _top(items, n):
    return items[:n] if isinstance(items, list) else items


def build_survey(tools) -> tuple[dict, int]:
    """(digest, bytes_touched). Compact by construction — every section is pre-ranked
    by the tools' own change-first ordering, so head-truncation keeps the movers."""
    bt = 0
    digest = {}

    svcs = tools.services()
    digest["services"] = svcs

    topo, b = tools.topology()
    bt += b
    if isinstance(topo, dict) and topo.get("edges"):
        digest["topology_slowest_edges"] = _top(topo["edges"], 8)

    tr, b = tools.traces()
    bt += b
    if isinstance(tr, dict) and "note" not in tr:
        ranked = sorted((x for x in tr.items() if isinstance(x[1], dict) and x[1].get("p95_ms")),
                        key=lambda kv: -(kv[1].get("p95_ms") or 0))
        digest["trace_latency_top"] = {k: v for k, v in ranked[:8]}

    lg, b = tools.logs()
    bt += b
    if isinstance(lg, dict) and "note" not in lg:
        digest["log_changes"] = {k: v for k, v in list(lg.items())[:8] if isinstance(v, dict)}

    mt, b = tools.metrics()
    bt += b
    if isinstance(mt, dict):
        if mt.get("top_movers"):
            digest["metric_top_movers"] = _top(mt["top_movers"], 8)
        if mt.get("host"):
            digest["host"] = mt["host"]

    kr, b = tools.kernel()
    bt += b
    if isinstance(kr, dict) and "note" not in kr:
        changed = {k: v for k, v in kr.items()
                   if isinstance(v, dict) and (v.get("changed") or v.get("wait_attribution"))}
        ranked = sorted(changed.items(),
                        key=lambda kv: -len(kv[1].get("changed") or []))
        digest["kernel_changes"] = {k: v for k, v in ranked[:8]}

    return digest, bt
