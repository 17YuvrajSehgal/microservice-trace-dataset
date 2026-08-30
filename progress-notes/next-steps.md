# Next steps (updated 29-08-2026, after the CPU cluster)

## State in one line
Branch `blueprints`, phase 1 = kernel only. **4 blueprints** built and measured on both
applications: co-tenant contention (v8), host CPU saturation (v2), service CPU throttle (v2),
datastore wait. Sock Shop **89%** on covered faults, Train Ticket **79%**. Total wrong answers
across 69 runs: **13**. Findings F1–F10 in `blueprints/docs/FINDINGS-phase1.md`.

## IMPORTANT standing decisions
- **A blueprint is a diagnostic guide, not a classifier.** Where a fault looks different on a
  different architecture, record BOTH pictures as `scenarios`. Do not chase one threshold
  that fits everything, and do not re-tune per application — that is fitting.
- **Measure first, then write.** No discriminator enters a blueprint before it is measured on
  our own data, and every new one must be checked against the OTHER families, not just its
  own. That check is what E1 exists for.
- **Runqueue delay is corroboration, never a deciding signal** (F2/F3). Retracted in all
  three CPU blueprints; do not reinstate without new evidence.

## Next (ordered)
1. **A3 `service-network-path` + A4 `frozen-dependency`, built as one pair.** They own
   **11 of the 13 remaining errors**. Build together — their discriminators only exist
   relative to each other and to the datastore blueprint, which is the lesson from F1.
2. **Fix socket peer attribution first**, since A3/A4 depend on it. F5 says what to change:
   normalise the flow to a 5-tuple and key on the well-known port; cap gaps at ~200 ms so
   idle time cannot enter; only measure where our process is the client; and account for
   **toxiproxy sitting in the datastore path** — the kernel-visible peer is the proxy.
3. **A5 `healthy-baseline`** — the no-fault runs now pass, but "nothing matches" should be a
   verdict the library reaches on purpose rather than by nothing firing.
4. **E3 relative discriminators** — express each signal against the system's own baseline and
   spread. Absolute cores already transfer; percentages do not.
5. Tier B when Tier A closes: host memory pressure, host disk saturation, async queue backlog
   (Sock-Shop-only, so it cannot be cross-app validated — state that limit).

## Don't rediscover
- **`anomaly_mem` reading as co-tenant is not a rule defect.** The memory-stress recipe runs a
  `stress-ng` container that genuinely takes ~1 core. Our traces have **no `mm_*` or `kmem_*`
  tracepoints**, so this cannot be separated from kernel data alone. Waits for a later phase.
- **Train Ticket CPU caps have no host-level signal at all** (0.8314 → 0.8316). Recorded as a
  blueprint scenario pointing at cgroup `cpu.stat`. Do not go looking for it in host aggregates.
- **babeltrace accepts an end hour past 24** and reads it as the next day, but rejects a window
  whose end is earlier than its begin. Do not "fix" `shift()` with a modulo — that breaks it.
- Baselines differ per app: Sock Shop idles at 0.48 utilisation on 12 CPUs, Train Ticket at
  0.82 on 16.
- Public RCA datasets (RCAEval 735 cases, LEMMA-RCA, LO2) carry **no kernel traces**, verified.
  Phase-1 external validation is not available; robustness comes from our own 110 runs.
- Cluster cost: kernel-only pack ~279 s per run against 367–539 s with spans. Re-deciding is
  free once packs carry `oncpu` — only decoding is expensive.
- Installing cluster scripts: use `wsl ssh trillium 'cat > path' <<'EOF'`. Inline `$VAR` and
  `$(...)` through `wsl ssh` get eaten (hit this 3 times this session).
