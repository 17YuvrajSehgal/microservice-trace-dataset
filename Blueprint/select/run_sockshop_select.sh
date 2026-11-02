#!/bin/bash
# Run the SELECTOR (router) blueprint over every Sock Shop run across the 4 evaluable fault
# families + the 10 normal controls, to measure how often the agent picks the right blueprint
# with no ground truth. Login node, 6 concurrent. svc_mem_cap excluded (no memcg tracepoints).
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
export RCA_PROVIDER=openrouter RCA_MODEL=openai/gpt-6-luna
export ABL_WORKER_STEPS=20 ABL_THREAD_BUDGET=150000
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
export PY="$HOME/agentv2venv/bin/python"
export BP=Blueprint/select/README_v1.md
export O=/scratch/yuvraj17/stratatrace/bp_eval/select/sockshop
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop
MAN=/scratch/yuvraj17/stratatrace/bp_eval/select/manifest.txt
mkdir -p "$(dirname "$MAN")" "$O"
: > "$MAN"
for fam in svc_cpu_cap noisy_neighbor slow_db svc_net normal; do
  for d in "$D/$fam"/*/; do
    case "$d" in *_metrics/) continue;; esac
    printf '%s\t%s\n' "$fam" "${d%/}" >> "$MAN"
  done
done
echo "runs to route: $(wc -l < "$MAN")"

run_one() {
  fam="$1"; rd="$2"; rid="$(basename "$rd")"
  mkdir -p "$O/$fam/$rid"
  "$PY" Blueprint/eval/eval_one.py --run-dir "$rd" --blueprint "$BP" --problem "$fam" \
    --index-root "$CTF_INDEX_ROOT" --out "$O/$fam/$rid" --transcript "$O/$fam/$rid/t.json" \
    > "$O/$fam/$rid/log" 2>&1
  echo "done $fam/$rid"
}
export -f run_one

# 6 at a time; each manifest line is family<TAB>run_dir -> $0 $1
cat "$MAN" | xargs -P 6 -L 1 bash -c 'run_one "$0" "$1"'
echo "##### SELECT SOCKSHOP DONE #####"
