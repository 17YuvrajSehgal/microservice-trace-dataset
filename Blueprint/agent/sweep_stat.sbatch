#!/bin/bash
# Full statistical-baseline degradation sweep (no API): every fault incident of both apps × the
# 'all' condition grid (trace/metric/log/kernel/compensate axes). Parallel per-(app,family) across
# the node; each run loads once and evaluates all conditions. Then analyze.py prints RQ1/RQ3 tables.
# Submit:  sbatch agentic-rca/sweep_stat.sbatch      Watch: tail -f /scratch/yuvraj17/strata-sweep-<jid>.out
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-sweep
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=03:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-sweep-%j.out
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
module load python/3.11 >/dev/null 2>&1; module load arrow/19.0.1 >/dev/null 2>&1
source .venv/bin/activate
OUT=agentic-rca/results/sweep; mkdir -p "$OUT"
echo "== sweep start $(date) =="

# (app, family) task list — skip baseline dirs (normal/lttng_only have no ground_truth)
TASKS="$OUT/_tasks.txt"; : > "$TASKS"
for app in trainticket sockshop; do
  for d in /scratch/yuvraj17/stratatrace/data/agentic-runs/$app/*/; do
    fam=$(basename "$d")
    case "$fam" in normal|lttng_only|*_metrics) continue;; esac   # skip baselines + aux metric dirs
    echo "$app $fam" >> "$TASKS"
  done
done
echo "== $(wc -l < "$TASKS") (app,family) tasks, PAR=${PAR:-12} =="

xargs -P "${PAR:-12}" -L1 -a "$TASKS" bash -c '
  app=$0; fam=$1
  python agentic-rca/evaluate.py --app "$app" --families "$fam" --method stat --grid all \
     --out "agentic-rca/results/sweep/${app}_${fam}.json" > "agentic-rca/results/sweep/${app}_${fam}.log" 2>&1 \
     && echo "OK   $app/$fam" || echo "FAIL $app/$fam"
'
echo "== sweep done $(date); aggregating =="
python agentic-rca/analyze.py "agentic-rca/results/sweep/*.json"
