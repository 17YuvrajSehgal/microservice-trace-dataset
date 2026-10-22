# eval — matched-blueprint evaluation

Measures **how often the agent detects a fault when handed the correct blueprint**. Everything
runs from the `Blueprint/` tree: the agent is `Blueprint/agent`, the blueprints are
`Blueprint/latency/*/README_v1.md`, the scorer is here. No dependency on the old `agentic-rca`
harness or `blueprints/lib`.

## Files

| file | role |
|---|---|
| `eval_matrix.py` | driver: run one blueprint over all its matching runs, parallel, resumable, scoreboard |
| `eval_one.py` | one run: `Blueprint/agent` diagnose + score + `result.json` |
| `score.py` | detection scorer — reads ground truth, grades fault/where/window. Handles both dataset shapes (microservice `ground_truth.json`, agentic `meta/ground_truth.json`) |
| `datasets.py` | problem → blueprint path; discover matching runs that have an index |
| `nsmap.py` | pid_ns → container (copied, for microservice WHERE scoring) |

## Run it

```bash
# matched arm: correct blueprint on its problem
python eval_matrix.py --problem svc_mem_cap \
    --runs-root <dir with run dirs + ground truth> \
    --index-root <dir with <run_id>.tsv.gz> \
    --out results/svc_mem_cap --jobs 4

python eval_matrix.py --problem svc_mem_cap --runs-root ... --index-root ... --dry-run
```

- `--arm given` (default) hands over the correct blueprint; `--arm none` is the control.
- A run is picked only when its ground-truth family matches `--problem` AND its index exists.
- Resumable: a run whose `result.json` exists is skipped.
- `--budget-usd N` stops before exceeding a cost cap (GPT-6 Luna pricing; override with
  `PRICE_IN_PER_M` / `PRICE_OUT_PER_M`).

## What "detected" means

- **microservice** (fault localised to a service): right fault type AND the right component
  (service name, or a pid_ns that maps to the right container).
- **agentic** (cap on the whole run cgroup): right fault type (there is no victim service to
  name — the cap is on the agent's own process).
- **control** (uncapped baseline): detecting it = the agent says normal / does not cry wolf.

## Launch prerequisites

Each run needs its index (`<run_id>.tsv.gz`) under `--index-root`, with the run_id matching the
ground-truth directory. Build indexes with `blueprints/lib/build_ctf_index.py`
(`Blueprint/agent` has a copy of the reader). Microservice traces live on Trillium; agentic
kernel traces are on Zenodo (see `os-noise-for-agentic-ai/DATA.md`).
