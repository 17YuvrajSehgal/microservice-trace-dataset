# 22-10-2026

## Matched-blueprint evaluation harness, in Blueprint/eval
- User wants everything we use to reside in Blueprint/. Built a self-contained eval that drives
  Blueprint/agent + Blueprint/latency and scores detection - no dependency on agentic-rca or
  blueprints/lib (the old q2 harness scored the OLD agent's ranked_candidates, which agent_v2
  does not produce, so a verbatim copy would have been half-dead).
- Blueprint/eval/: eval_matrix.py (driver, parallel, resumable, scoreboard, budget cap),
  eval_one.py (diagnose+score one run), score.py (detection scorer for BOTH ground-truth shapes
  - microservice fault.target_service/scope, and agentic cpu_max/mem_limit caps incl. control
  vs fault), datasets.py (problem->blueprint, discover runs with an index), nsmap.py (copied).
- "detected": microservice = right fault AND right component (name or pid_ns->container via
  nsmap); agentic = right fault type (cap is on the whole cgroup, no victim service); control =
  agent says normal.
- PROVEN end to end on svc_cpu_cap_aggressive_steady_r1 (real ground truth): verdict "java in
  pid_ns 4026532538 / cpu_throttling", scored detected=True, where=container, window IoU 0.975.
  Cost $0.21 (1.98M in + 25k out at research defaults). The same Sock Shop trace that gave
  "unknown/other" before now lands correctly - the accumulated fixes (WSL babeltrace, date
  self-heal, sched_budget 256 fix) paid off.

## Launch readiness for the full 250-run matched eval
- Harness: READY.
- Blocker: each run needs its index (<run_id>.tsv.gz) co-located (by run_id) with its
  ground-truth dir. Today only the svc_cpu_cap sample lines up locally.
  - Microservice 80 runs: traces on Trillium -> build index-v2 there and run eval on Trillium
    (or pull indexes).
  - Agentic 170 runs: kernel traces are Zenodo-only (2.6 GB) -> download + build indexes with
    run_ids matching the meta/ dirs (NOT the demo's ext_* ids).
- Cost confirmed by the real run: ~$0.21/run research-default -> ~$52 for 250; ~half with the
  demo step cap. Fund $60 (matched) / $200 (full specificity matrix).
