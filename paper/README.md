# FSE 2027 draft — build notes

- `main.tex` — ACM `acmart` (sigconf). For double-blind submission switch the
  documentclass line to `\documentclass[sigconf,review,anonymous]{acmart}`.
- `sections/00-abstract.tex … 09-conclusion.tex` — one file per section.
- `references.bib` — entries marked `TODO-verify` need checking; several families of
  citations still to add (see file tail).
- `fse-draft.md` — the original markdown draft; the TODO tracker at its end is the
  authoritative list of pending experiments/figures.

Build: `latexmk -pdf main.tex` (TeX Live with acmart; not compiled on the Windows dev
box — verify on Overleaf or the cluster).

Red `[TODO: …]` markers in the PDF come from the `\todo{}` helper in `main.tex`;
strip before submission.

Numbers trace to: `../agentic-rca/RESULTS-v4-campaign.md`,
`RESULTS-agent-kernel-sweep.md`, `RESULTS-agent-trace-sweep.md`,
`RESULTS-agent-metric-log-sweeps.md`, `RESULTS-agent-interact-removal.md`,
`RESULTS-agent-sanitygate-masked.md`,
`RESULTS-nonllm-baselines.md`; transcripts + sha256 bundles on
`/project/def-naser2/yuvraj17/microservice-trace-dataset/artifacts/`.
