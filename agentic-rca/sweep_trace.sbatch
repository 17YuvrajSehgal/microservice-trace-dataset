#!/bin/bash
# RQ1 cliff baselines: the deliberately trace-dependent RCAEval methods (MicroRank + TraceRCA) over
# the TRACE-retention grid (full→5%). Unlike the flat metric methods, these should COLLAPSE as traces
# are sampled away — the RQ1 cliff evidence. Runs in .venv-rca (py3.12). Trace grid only (5 conds):
# the degraded conditions are cheap; only full-traces is slow on SS (2.6M spans).
# Submit: sbatch agentic-rca/sweep_trace.sbatch   Watch: tail -f /scratch/yuvraj17/strata-trace-<jid>.out
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-trace
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/strata-trace-%j.out
set -uo pipefail
cd /scratch/yuvraj17/microservice-trace-dataset
module load python/3.12 >/dev/null 2>&1; module load arrow/19.0.1 >/dev/null 2>&1
source /scratch/yuvraj17/.venv-rca/bin/activate
export TQDM_DISABLE=1
OUT=agentic-rca/results/sweep_trace; mkdir -p "$OUT"
echo "== trace-method sweep start $(date) =="

TASKS="$OUT/_tasks.txt"; : > "$TASKS"
for app in trainticket sockshop; do
  for d in /scratch/yuvraj17/agentic-runs/$app/*/; do
    fam=$(basename "$d"); case "$fam" in normal|lttng_only|*_metrics) continue;; esac
    for m in microrank tracerca; do echo "$app $fam $m" >> "$TASKS"; done
  done
done
echo "== $(wc -l < "$TASKS") (app,family,method) tasks, PAR=${PAR:-12} =="

xargs -P "${PAR:-12}" -L1 -a "$TASKS" bash -c '
  app=$0; fam=$1; m=$2
  python agentic-rca/evaluate.py --app "$app" --families "$fam" --method "$m" --grid trace \
     --out "agentic-rca/results/sweep_trace/${app}_${fam}_${m}.json" > "agentic-rca/results/sweep_trace/${app}_${fam}_${m}.log" 2>&1 \
     && echo "OK   $app/$fam/$m" || echo "FAIL $app/$fam/$m"
'
echo "== trace-method sweep done $(date) =="
ANALYZE_METRIC=service_hit python agentic-rca/analyze.py "agentic-rca/results/sweep_trace/*.json"
