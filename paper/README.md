# Supervisor progress report — build notes

- `main.tex` — plain `article` class; a readable progress report (approach, methods,
  results), NOT a venue paper. Build: `latexmk -pdf main.tex` (verified on the cluster's
  base TeX Live; no special classes needed).
- `sections/00-summary … 08-next, 10-appendix` — one file per report section, written
  for a reader with no prior context: no run identifiers, no condition codes, fault
  types in plain English.
- `fse-draft.md` — the archived research-paper draft + its TODO tracker (kept for the
  eventual paper; the paper-form LaTeX sections live in git history before 2026-08-18).
- `acmart.cls` / `ACM-Reference-Format.bst` — vendored for the future paper build;
  unused by the report.

Numbers trace to: `../agentic-rca/RESULTS-v4-campaign.md`,
`RESULTS-agent-kernel-sweep.md`, `RESULTS-agent-trace-sweep.md`,
`RESULTS-agent-metric-log-sweeps.md`, `RESULTS-agent-interact-removal.md`,
`RESULTS-agent-budget-sweep.md`, `RESULTS-agent-sanitygate-masked.md`,
`RESULTS-nonllm-baselines.md`; every diagnosis record + sha256 bundles on
`/project/def-naser2/yuvraj17/microservice-trace-dataset/artifacts/`.
