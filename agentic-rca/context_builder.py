#!/usr/bin/env python3
"""Investigation Context Builder (v4, Phase 1) — deterministic evidence survey.

Runs the same no-filter queries the agent's SURVEY step would run and writes each
finding into the Shared Investigation Context as a typed CLAIM with provenance
(shared_context.py). No LLM, no ground truth — pure tool output.

Consumers: the skill selector routes on sic.digest() (masked), and with brief
injection enabled the diagnosis agent receives shared_context.format_brief() of the
masked digest. build_survey() remains as the digest-shaped compatibility view.
"""
from __future__ import annotations

from shared_context import SharedInvestigationContext


def build_context(tools, run_id: str = "") -> tuple[SharedInvestigationContext, int]:
    """(SharedInvestigationContext, bytes_touched). Every section is pre-ranked by the
    tools' own change-first ordering, so head-truncation keeps the movers."""
    sic = SharedInvestigationContext(run_id)
    bt = 0

    svcs = tools.services()
    sic.add("inventory", "system", "services_present", {"services": svcs},
            f"{len(svcs)} services visible across modalities",
            {"tool": "list_services", "modality": "all"})

    topo, b = tools.topology()
    bt += b
    if isinstance(topo, dict):
        for e in (topo.get("edges") or [])[:8]:
            sic.add("topology_edge", str(e.get("callee")), "slow_edge", e,
                    f"{e.get('caller')}->{e.get('callee')} p95 "
                    f"{e.get('p95_baseline_ms')}->{e.get('p95_incident_ms')}ms "
                    f"(x{e.get('slowdown_x')})",
                    {"tool": "topology", "modality": "traces"})

    tr, b = tools.traces()
    bt += b
    if isinstance(tr, dict) and "note" not in tr:
        ranked = sorted((x for x in tr.items() if isinstance(x[1], dict) and x[1].get("p95_ms")),
                        key=lambda kv: -(kv[1].get("p95_ms") or 0))
        for svc, v in ranked[:8]:
            sic.add("latency", str(svc), "server_latency", v,
                    f"{svc} p95 {v.get('p95_ms')}ms (n={v.get('n')})",
                    {"tool": "traces", "modality": "traces"})

    lg, b = tools.logs()
    bt += b
    if isinstance(lg, dict) and "note" not in lg:
        for svc, v in list(lg.items())[:8]:
            if not isinstance(v, dict):
                continue
            sic.add("log_change", str(svc), "err_rate_change", v,
                    f"{svc} errors/min {v.get('err_per_min_baseline')}->"
                    f"{v.get('err_per_min_incident')} (x{v.get('change_x')}, "
                    f"{len(v.get('new_signatures') or [])} new sigs)",
                    {"tool": "logs", "modality": "logs"})

    mt, b = tools.metrics()
    bt += b
    if isinstance(mt, dict):
        for m in (mt.get("top_movers") or [])[:8]:
            sic.add("metric_mover", str(m.get("container")), str(m.get("signal")), m,
                    f"{m.get('container')} {m.get('signal')} "
                    f"{m.get('baseline')}->{m.get('incident')}",
                    {"tool": "metrics", "modality": "metrics"})
        for k, v in (mt.get("host") or {}).items():
            sic.add("host_signal", "host", str(k), v,
                    f"host {k} {v.get('baseline')}->{v.get('incident')}"
                    if isinstance(v, dict) else f"host {k}",
                    {"tool": "metrics", "modality": "metrics"})

    kr, b = tools.kernel()
    bt += b
    if isinstance(kr, dict) and "note" not in kr:
        changed = {k: v for k, v in kr.items()
                   if isinstance(v, dict) and (v.get("changed") or v.get("wait_attribution"))}
        ranked = sorted(changed.items(), key=lambda kv: -len(kv[1].get("changed") or []))
        for svc, v in ranked[:8]:
            if v.get("changed"):
                top = v["changed"][0]
                sic.add("kernel_change", str(svc), "kpi_change", v["changed"],
                        f"{svc} {top.get('kpi')} {top.get('baseline')}->"
                        f"{top.get('incident')} (x{top.get('x')}) +{len(v['changed']) - 1} more",
                        {"tool": "kernel", "modality": "kernel"})
            if v.get("wait_attribution"):
                wa = v["wait_attribution"]
                sic.add("wait_attribution", str(svc), "wait_profile", wa,
                        f"{svc} wait rule-out {wa.get('rule_out_pct')} "
                        f"hint={wa.get('verdict_hint')}",
                        {"tool": "kernel", "modality": "kernel-L2"})

    return sic, bt


def build_survey(tools) -> tuple[dict, int]:
    """Compatibility view: the digest dict (same shape as before) + bytes touched."""
    sic, bt = build_context(tools)
    return sic.digest(), bt
