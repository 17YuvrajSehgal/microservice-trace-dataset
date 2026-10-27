#!/bin/bash
# Full Sock Shop re-run on the fixed stack (all 4 evaluable blueprints), login node.
# Apples-to-apples + regression check after the blueprint/tool fixes. svc_mem_cap is
# excluded (no memcg tracepoints in the trace - not evaluable).
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
export RCA_PROVIDER=openrouter RCA_MODEL=openai/gpt-6-luna
export ABL_WORKER_STEPS=20 ABL_THREAD_BUDGET=150000
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
PY="$HOME/agentv2venv/bin/python"
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop
O=/scratch/yuvraj17/stratatrace/bp_eval/results_v2/sockshop

run_family() {
  local prob="$1" bp="$2"
  echo "### $prob ###"
  "$PY" Blueprint/eval/eval_matrix.py --problem "$prob" --runs-root "$D" \
    --index-root "$CTF_INDEX_ROOT" --out "$O/$prob" --no-controls --jobs 6
}

run_family svc_cpu_cap    1_svc_cpu_cap
run_family noisy_neighbor 2_noisy_neighbor
run_family slow_db        3_slow_db
run_family svc_net        5_svc_net
echo "##### SS FULL RERUN DONE #####"
