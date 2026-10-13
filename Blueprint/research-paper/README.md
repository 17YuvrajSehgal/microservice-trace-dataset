# Research paper — OS Noise for Agentic AI

`paper.tex` — the draft paper. Self-contained, builds with plain pdfLaTeX
(only standard packages: geometry, booktabs, amsmath, amssymb, graphicx,
hyperref, caption).

## Build

```bash
pdflatex paper.tex && pdflatex paper.tex   # twice, for refs
```

Or `latexmk -pdf paper.tex`. No TeX engine is installed on the dev box, so
build on a machine with TeX Live / MiKTeX (or Overleaf: upload `paper.tex`
and the `figures/` folder). Packages used (all standard): geometry,
booktabs, multirow, amsmath, amssymb, amstext, graphicx, hyperref, caption.

## Figures and tables

- `figures/fig_{cpu,threads,memory,io}.pdf` are embedded by the paper;
  `.png` copies are provided for quick preview without building.
- `make_figures.py` regenerates all four figures (matplotlib, Okabe--Ito
  colorblind-safe palette). `make_data.py` recomputes every table/figure
  number (median + min--max across reps) straight from the run data, so the
  paper's figures match the data exactly. Run both from this directory;
  they import the analyzer from `../latency/1_svc_cpu_cap/.../analysis`.

## Numbers

All figures come from the four `../latency/*/RESULTS.md` and their
`analysis/results*.json`. Re-derive with the `aggregate_*.py` scripts over
the run data. 130 campaign runs total (CPU 40, threads 20+6, memory 32+12,
I/O 20).

## Status

Draft. Pending: align structure/citations to the OS-noise papers Naser is
sending; add real \cite{} references and (optionally) a dose-response
figure per problem.
