# Decisions — 16-08-2026

## As-built architecture diagram added to new_design.md §2b
Mermaid diagram of the current system (built components only), color-mapped to the supervisor's
requirements diagram, with a legend of what maps 1:1, what's partial, and what's absent.

## Mined all 71 old runs (zero API cost) → readiness verdict + 3 boundary fixes (f242957)
Question (Yuvraj): learn from old runs or go straight to the full run? Mined every results dir
(gate_v3 + all v4 rounds): selector confusion matrix, svc-right/fault-wrong evidence audit,
repeat-variance, trajectory stats, skill-influence table.

**Going well:** host-family selection 7/7, svc_cpu_cap + dependency_outage 3/3; selection quality
gates outcome (sel_ok → both 8/11; sel_wrong → both 3/14 — the lever, quantified); brief mode ~11
calls vs 18–20 for skills-without-brief; Azure prompt cache already covers 68% of input tokens
(~25k in / 500 out per incident → full S0/S1/S2 campaign ≈ 1.7M in, cheap; the degradation sweep
is the only expensive item).

**Systematic failures (≥2–3 repeats each) → three generic skill-boundary fixes applied:**
1. svc_mem_cap → frozen-dependency (3/3): silence-direction missing — frozen = callers keep
   TRYING (timeouts toward it); callers quiet too = starved victim, look upstream.
2. noisy_neighbor → cpu_saturation/throttling (×3): the co-tenant is itself CPU-capped, so
   limit_signals shows ITS throttle → rule: throttled container with NO call-path edges = co-tenant.
3. anomaly_net → disk_io (×3): block-LATENCY wobble read as disk — rule: disk_io requires
   throughput/io_time rise, latency percentiles alone prove nothing.
NOT chased: error_storm → dependency_outage (agent mechanism descriptions are accurate — injected
connection resets; handle as a mechanism-correct secondary metric in analysis, not skill edits).

**Also answered (16-08, cost design):** more skills = no (coverage complete; selection is the
bottleneck); more agent observability = capture already 100% (and Azure chat completions return
zero hidden-CoT — Responses API not worth the behavior risk); MCP = interface, zero accuracy
effect, defer.

## Campaign design (ready after these fixes)
- **Primary skill condition = skills+brief** (never tested together; brief removes the re-survey
  the verify-first step forces → expect ~40% cost cut in skills mode and same/better accuracy).
- Repeats r=3 ONLY on the 5 flip-prone incidents found by the variance audit (tt_slow_db,
  tt_dependency_outage ×2 configs, tt_svc_cpu_cap, ss svc_mem_cap-brief); r=1 elsewhere.
- Conditions: S0 (off), S0+brief, S1(=skills+brief), S2 LOFO(+brief) over the 23 gate incidents.
- Analysis adds a mechanism-correct secondary metric (label-strict remains primary).
