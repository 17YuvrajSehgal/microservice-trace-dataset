# Next steps (updated 17-08-2026, post kernel-tier sweep)

## State in one line
Platform complete and audited end-to-end. Results of record: **S0b (Context Builder brief) 87/61/57
@ $0.01/incident**; skills net-negative pending selector redesign (S1/S2 campaigns); SS-L2 within
A/A noise (campaign 2; variance ±9 pts quantified); **kernel-tier sweep on the agent done**
(kAll 61 both @9.1 calls · kNone 57 @12.2 · kL1-only 43 — kernel = efficiency + db-typing;
partial kernel worse than none; H2 unconfirmed at full telemetry). All artifacts sha256-bundled
on /project. Branch `new-agentic-architecture`.

## IMPORTANT standing decision
The degradation program now runs on **frozen v4-s0b** (brief on, skills off) — the kernel axis
already did. Do NOT mix axes across agent versions; the old "sweep on frozen v3/master" plan is
superseded (record in decisions when the next axis runs).

## Next (ordered)
1. **RQ1 axes on the agent**: trace (100→5%), metric (5s→60s), log (ALL→ERROR) — same ksweep
   driver pattern, `--grid trace|metric|log --brief`; ~$1-2 and ~2-4h per axis. Where are the
   cliffs the flat baselines lack?
2. **Kernel × degraded-traces interaction (H2's real test)**: add a small grid
   (e.g. trace010 × {kAll, kNone} + trace025 variants) to evaluate.GRIDS; kernel's value should
   GROW as traces thin — this is the paper's kernel-compensation claim, properly tested.
3. **Zero-cost analyses**: RQ4 Pareto join (bytes/tokens/$ already per-row + overhead numbers);
   mechanism-correct secondary metric in analyze; formal RQ2 write-up (dead-kernel-hammering 30%,
   broad-front compensation, escalation metrics across axes once RQ1 runs).
4. **fault_catalog §7 amendments** (pre-registration discipline): H2-at-full-telemetry outcome +
   the F3/F8 memory-tracepoint wording drift found in the 14-08 doc audit.
5. **Supervisor packet + Naser gate**: as-built diagram (new_design.md §2b), campaign table,
   kernel-sweep findings K1-K4, skills negative result, §7 open questions.
6. **Small fixes queue** (before the next axis, they're one-liners): global "kernel telemetry
   unavailable" tool answer (kills the 30% wasted calls under kNone — also makes RQ2 cleaner:
   measure before/after); IP→service reverse-map for peer-edge callees.
7. **Selector redesign** (unblocks skills; product track, not paper-critical): iterate via digest
   replay over the 200+ saved surveys — pennies; two-stage verify-against-SIC design drafted in
   RESULTS-v4-campaign.md.
8. Later: cross-app skill transfer, mined skills, assistant-mode eval, MCP face, Trace Compass
   bridge (kernel L0 is native CTF).
9. **Deadlines: MSR abstract Nov 5, paper Nov 10.** Write-up sources: RESULTS-v4-campaign.md,
   RESULTS-agent-kernel-sweep.md, RESULTS-agent-sanitygate-masked.md, RESULTS-nonllm-baselines.md.

## Don't rediscover
- Driver/status/report pattern: ksweep_driver.sh + *_status.sh (install cluster scripts ONLY via
  `wsl ssh trillium 'cat > path' <<'EOF'` — inline `$(...)` through wsl breaks, 4th time).
- Costs: ~$0.01-0.02/incident, 50-73% cache; sweeps ≈ $1/axis. Login node only, ~2min/diagnosis.
- Variance: ±9 pts single-run per-condition; repeats only where a claim is quoted.
- v3 remains frozen on master (historical baseline); v4 work on new-agentic-architecture.
