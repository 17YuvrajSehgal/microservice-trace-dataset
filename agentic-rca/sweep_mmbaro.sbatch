#!/bin/bash
# Full RCAEval / Multi-source BARO (mmbaro) degradation sweep (RCA method #2, no API): every fault
# incident of both apps × the 'all' condition grid. Runs in .venv-rca (py3.12 + RCAEval + stratatrace).
# Kernel fold is a no-op here (no pyarrow in .venv-rca) → mmbaro is M+L+T; kernel-tier conditions
# collapse to full. Then analyze.py prints the Top-1-localization (AC@1) RQ1/RQ3 tables.
# Submit:  sbatch agentic-rca/sweep_mmbaro.sbatch     Watch: tail -f /scratch/yuvraj17/strata-mmbaro-<jid>.out
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-mmbaro
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=03:00:00
#SBATCH --output=/scratch/yuvraj17/strata-mmbaro-%j.out
set -uo pipefail
cd /scratch/yuvraj17/microservice-trace-dataset
module load python/3.12 >/dev/null 2>&1
source /scratch/yuvraj17/.venv-rca/bin/activate
OUT=agentic-rca/results/sweep_mmbaro; mkdir -p "$OUT"
echo "== mmbaro sweep start $(date) | python=$(python --version 2>&1) =="

TASKS="$OUT/_tasks.txt"; : > "$TASKS"
for app in trainticket sockshop; do
  for d in /scratch/yuvraj17/agentic-runs/$app/*/; do
    fam=$(basename "$d")
    case "$fam" in normal|lttng_only|*_metrics) continue;; esac
    echo "$app $fam" >> "$TASKS"
  done
done
echo "== $(wc -l < "$TASKS") (app,family) tasks, PAR=${PAR:-12} =="

xargs -P "${PAR:-12}" -L1 -a "$TASKS" bash -c '
  app=$0; fam=$1
  python agentic-rca/evaluate.py --app "$app" --families "$fam" --method mmbaro --grid all \
     --out "agentic-rca/results/sweep_mmbaro/${app}_${fam}.json" > "agentic-rca/results/sweep_mmbaro/${app}_${fam}.log" 2>&1 \
     && echo "OK   $app/$fam" || echo "FAIL $app/$fam"
'
echo "== mmbaro sweep done $(date); aggregating (Top-1 localization) =="
ANALYZE_METRIC=service_hit python agentic-rca/analyze.py "agentic-rca/results/sweep_mmbaro/*.json"
