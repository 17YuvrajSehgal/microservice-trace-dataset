#!/bin/bash
# Run selector C (robust, mechanism-first) over Sock Shop. Resumable (skips cells with a
# result.json). Optional args = family filter (default: all 5). 6 concurrent.
#   bash run_select_c.sh                       # all 42
#   bash run_select_c.sh svc_cpu_cap svc_net   # just the failure families (fast validation)
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
# provider/model can be pre-set in the env (e.g. RCA_PROVIDER=claude RCA_MODEL=claude-opus-5)
export RCA_PROVIDER="${RCA_PROVIDER:-openrouter}"
[ "$RCA_PROVIDER" = openrouter ] && export RCA_MODEL="${RCA_MODEL:-openai/gpt-6-luna}"
export ABL_WORKER_STEPS="${ABL_WORKER_STEPS:-20}" ABL_THREAD_BUDGET="${ABL_THREAD_BUDGET:-150000}"
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
export PY="$HOME/agentv2venv/bin/python"
export BASE=/scratch/yuvraj17/stratatrace/bp_eval/select
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop
mkdir -p "$BASE"
fams=("$@"); [ ${#fams[@]} -eq 0 ] && fams=(svc_cpu_cap noisy_neighbor slow_db svc_net normal)

MAN="$BASE/.manifest_${SEL_ARM:-sockshop_c}.txt"; : > "$MAN"   # per-arm: two arms can run at once
for fam in "${fams[@]}"; do
  for d in "$D/$fam"/*/; do case "$d" in *_metrics/) continue;; esac
    rid="$(basename "${d%/}")"
    [ -f "$BASE/${SEL_ARM:-sockshop_c}/$fam/$rid/result.json" ] || printf '%s\t%s\n' "$fam" "${d%/}" >> "$MAN"
  done
done
n=$(wc -l < "$MAN"); echo "to run: $n  (families: ${fams[*]})"
[ "$n" -eq 0 ] && { echo "nothing to do"; exit 0; }

run_one() {
  fam="$1"; rd="$2"; rid="$(basename "$rd")"
  out="$BASE/${SEL_ARM:-sockshop_c}/$fam/$rid"; mkdir -p "$out"
  "$PY" Blueprint/eval/eval_one.py --run-dir "$rd" --blueprint Blueprint/select_c/README_v1.md \
    --problem "$fam" --index-root "$CTF_INDEX_ROOT" --out "$out" --transcript "$out/t.json" > "$out/log" 2>&1
  echo "  done $fam/$rid"
}
export -f run_one
cat "$MAN" | xargs -P "${SEL_PAR:-6}" -L 1 bash -c 'run_one "$0" "$1"'
echo "##### SELECT C DONE #####"
