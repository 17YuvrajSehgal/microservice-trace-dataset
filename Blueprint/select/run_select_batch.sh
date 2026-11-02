#!/bin/bash
# Resumable, batched A-vs-B selector run. Each call runs up to N cells that do NOT yet have a
# result.json, FOREGROUND (so the caller sees it finish), then reports progress. Safe against
# tunnel drops: completed cells persist, a dropped batch just re-runs its unfinished cells.
#   bash run_select_batch.sh [N]      # default N=6
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
export RCA_PROVIDER=openrouter RCA_MODEL=openai/gpt-6-luna
export ABL_WORKER_STEPS=20 ABL_THREAD_BUDGET=150000
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
export PY="$HOME/agentv2venv/bin/python"
export BASE=/scratch/yuvraj17/stratatrace/bp_eval/select
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop
N="${1:-6}"
mkdir -p "$BASE"

MAN="$BASE/manifest_ab.txt"
if [ ! -s "$MAN" ]; then
  : > "$MAN"
  for tag in a b; do for fam in svc_cpu_cap noisy_neighbor slow_db svc_net normal; do
    for d in "$D/$fam"/*/; do case "$d" in *_metrics/) continue;; esac
      printf '%s\t%s\t%s\n' "$tag" "$fam" "${d%/}" >> "$MAN"; done
  done; done
fi
total=$(wc -l < "$MAN")

# remaining = manifest lines whose result.json is missing
rem="$BASE/.remaining.txt"; : > "$rem"
while IFS=$'\t' read -r tag fam rd; do
  rid="$(basename "$rd")"
  [ -f "$BASE/sockshop_${tag}/${fam}/${rid}/result.json" ] || printf '%s\t%s\t%s\n' "$tag" "$fam" "$rd" >> "$rem"
done < "$MAN"
nrem=$(wc -l < "$rem")
done_now=$(( total - nrem ))
echo "progress: $done_now / $total done; $nrem remaining; this batch runs up to $N"
[ "$nrem" -eq 0 ] && { echo "##### AB ALL DONE #####"; exit 0; }

run_one() {
  tag="$1"; fam="$2"; rd="$3"; rid="$(basename "$rd")"
  out="$BASE/sockshop_${tag}/${fam}/${rid}"; mkdir -p "$out"
  "$PY" Blueprint/eval/eval_one.py --run-dir "$rd" --blueprint "Blueprint/select_${tag}/README_v1.md" \
    --problem "$fam" --index-root "$CTF_INDEX_ROOT" --out "$out" --transcript "$out/t.json" > "$out/log" 2>&1
  echo "  done ${tag} ${fam}/${rid}"
}
export -f run_one

head -n "$N" "$rem" | xargs -P "$N" -L 1 bash -c 'run_one "$0" "$1" "$2"'
now=$(find "$BASE/sockshop_a" "$BASE/sockshop_b" -name result.json 2>/dev/null | wc -l)
echo "batch finished; results now: $now / $total"
