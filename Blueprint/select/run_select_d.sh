#!/bin/bash
# Run selector D (one router for container + bare-metal hosts) over Sock Shop v2 runs. Resumable
# (skips cells with a result.json). Args = family filter; default = the 5 selector-C families plus
# the two lock families that only D can route. SEL_PAR concurrent (default 6).
#   bash run_select_d.sh                                  # all 52
#   bash run_select_d.sh lock_contention priority_inversion
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
export RCA_PROVIDER="${RCA_PROVIDER:-openai}" RCA_MODEL="${RCA_MODEL:-qwen3.8-27b}"
export ABL_WORKER_STEPS="${ABL_WORKER_STEPS:-20}" ABL_THREAD_BUDGET="${ABL_THREAD_BUDGET:-150000}"
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
export PY="$HOME/agentv2venv/bin/python"
export BASE=/scratch/yuvraj17/stratatrace/bp_eval/select
export ARM="${SEL_ARM:-sockshop_d}"
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop
mkdir -p "$BASE"
fams=("$@"); [ ${#fams[@]} -eq 0 ] && fams=(svc_cpu_cap noisy_neighbor slow_db svc_net normal lock_contention priority_inversion)

MAN="$BASE/.manifest_${ARM}.txt"; : > "$MAN"
for fam in "${fams[@]}"; do
  for d in "$D/$fam"/*/; do case "$d" in *_metrics/) continue;; esac
    rid="$(basename "${d%/}")"
    [ -f "$BASE/$ARM/$fam/$rid/result.json" ] || printf '%s\t%s\n' "$fam" "${d%/}" >> "$MAN"
  done
done
n=$(wc -l < "$MAN"); echo "to run: $n  (families: ${fams[*]})"
[ "$n" -eq 0 ] && { echo "nothing to do"; exit 0; }

run_one() {
  fam="$1"; rd="$2"; rid="$(basename "$rd")"
  out="$BASE/$ARM/$fam/$rid"; mkdir -p "$out"
  "$PY" Blueprint/eval/eval_one.py --run-dir "$rd" --blueprint Blueprint/select_d/README_v1.md \
    --problem "$fam" --index-root "$CTF_INDEX_ROOT" --out "$out" --transcript "$out/t.json" > "$out/log" 2>&1
  echo "  done $fam/$rid"
}
export -f run_one
cat "$MAN" | xargs -P "${SEL_PAR:-6}" -L 1 bash -c 'run_one "$0" "$1"'
echo "##### SELECT D DONE #####"
