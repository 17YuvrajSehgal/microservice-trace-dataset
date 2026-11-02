#!/bin/bash
# Experiment 2: selector A (drill-to-root) vs B (fingerprint panel), head-to-head over the same
# 42 Sock Shop runs. FLAT structure (top-level run_one, exported once) - the earlier nested
# run_router/export-f version hung before any cell ran. Login node, 6 concurrent, setsid-safe.
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
export RCA_PROVIDER=openrouter RCA_MODEL=openai/gpt-6-luna
export ABL_WORKER_STEPS=20 ABL_THREAD_BUDGET=150000
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
export PY="$HOME/agentv2venv/bin/python"
export BASE=/scratch/yuvraj17/stratatrace/bp_eval/select
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop
mkdir -p "$BASE"

MAN="$BASE/manifest_ab.txt"
: > "$MAN"
for tag in a b; do
  for fam in svc_cpu_cap noisy_neighbor slow_db svc_net normal; do
    for d in "$D/$fam"/*/; do
      case "$d" in *_metrics/) continue;; esac
      printf '%s\t%s\t%s\n' "$tag" "$fam" "${d%/}" >> "$MAN"
    done
  done
done
echo "cells to run: $(wc -l < "$MAN")"

run_one() {
  tag="$1"; fam="$2"; rd="$3"; rid="$(basename "$rd")"
  bp="Blueprint/select_${tag}/README_v1.md"
  out="$BASE/sockshop_${tag}/$fam/$rid"
  mkdir -p "$out"
  "$PY" Blueprint/eval/eval_one.py --run-dir "$rd" --blueprint "$bp" --problem "$fam" \
    --index-root "$CTF_INDEX_ROOT" --out "$out" --transcript "$out/t.json" > "$out/log" 2>&1
  echo "done $tag $fam/$rid"
}
export -f run_one

# each manifest line is tag<TAB>fam<TAB>run_dir -> $0 $1 $2
cat "$MAN" | xargs -P 6 -L 1 bash -c 'run_one "$0" "$1" "$2"'
echo "##### AB ALL DONE #####"
