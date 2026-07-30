# Next steps — after 30-07-2026 (agent-first MVP, branch `agentic-tracing`)

## State: robust demo MVP COMPLETE and validated end-to-end

All under `agent-first-mvp/`. VM `stratatrace-collector` (us-east1-d), stack UP.
Dataset safe: all analysis READ-ONLY on `~/traces`; work in `~/mvp_work/`, live in
`~/mvp_captures/`; snapshot `stratatrace-dataset-safe-20260729`.

**Working, validated:**
- **4 faults, 4 different decisive modalities, all correct vs hidden ground truth (replay):**
  slow_db → kernel+traces (31.8×) · noisy_neighbor → kernel-only (13.3×) ·
  dependency_outage → traces+kernel (27.6×) · error_storm → logs+metrics (2.0×).
- **Engine**: `wait_attribution.py` (TGID identity + rule-out buckets), `modalities.py`
  (spans/logs/metric, byte-counted), `rca.py` (deterministic verdict + optional LLM
  narration), `phase2.py` (orchestrator + scoped-vs-undirected sizing).
- **Agentic interface**: `mcp_server.py` (fastmcp; 5 tools verified) + `.mcp.json`;
  `demo_cli.py` deterministic fallback (discover/phase1/run).
- **Dashboards**: `dashboard/render.py` (kernel-instrument verdict page) + `site.py`
  (benchmark + catalog landing). Pre-cached in `~/mvp_work/results/` (+ Artifacts).
- **Live mode**: `live_capture.py` — scoped LTTng session (only declared events) + tested
  fault inject under load + `finally` cleanup + chown; verified producing the correct
  live verdict from fresh data.
- Runbook: `DOCS/agent-first-mvp-demo-runbook.md`.

## Do first next session
1. **Live trace signal is thin** (catalogue spans n≈0 in a 30s live window — OTel collector
   batch flush). Kernel carries the live verdict correctly, but to make the live trace
   modality land: raise the collector's batch flush or the OTLP drain, or lengthen the
   injection window; consider reading the collector's flush interval.
2. **Wire the 5th skill** (cpu-saturation-rca / anomaly_cpu) — decompress its kernel copy,
   add gatherer+decider (stress-ng aggressor on-CPU + host-CPU metric). Then the benchmark
   is 5/5.
3. **Honesty guard in `rca.decide_*`**: if the kernel evidence is empty (0 tids / all-zero),
   lower confidence / flag "insufficient data" rather than returning the default hypothesis
   (currently only mattered on the pre-chown live bug, but worth hardening).
4. Optional: LLM narration via `claude` CLI (deterministic verdict stays authoritative).

## Demo-day checklist (see runbook)
- `git pull` on VM; `docker ps` ~19 up; `python3 -c "import fastmcp"`.
- Pre-cache: `~/mvp_work/results/{index,db-slowness-rca,noisy-neighbor-rca,
  dependency-outage-rca,error-storm-rca}.html` + `db-slowness-rca-live.html`.
- Fallback ladder: live→replay→pre-cached HTML→Artifact.
- Stop the VM when done (costs money):
  `gcloud compute instances stop stratatrace-collector --zone=us-east1-d`.

## Artifacts (shareable)
- Hero verdict: https://claude.ai/code/artifact/ef4477af-e7f4-4b21-be2f-201b51cdcca6
- 4-fault benchmark: https://claude.ai/code/artifact/77176901-8058-4fe3-9aa9-43e1178ff153
