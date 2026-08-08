#!/bin/bash
# derive_l2_working_set.sh — derive kernel L2 (wait-attribution) for every run of an app and drop
# kernel_l2.jsonl next to the already-extracted small modalities in the /scratch working tree.
# L2 needs the raw L0 CTF (in the /project archives) + babeltrace2 (local build on this cluster).
# Same per-service method as derive_kernel_l2.py produced for the Sock Shop test file — no logic
# change, just batched. Resumable: a run whose kernel_l2.jsonl already exists is skipped.
#
#   bash derive_l2_working_set.sh trainticket        # all 12 recipes
#   PAR=8 bash derive_l2_working_set.sh sockshop
set -uo pipefail
APP="${1:?usage: derive_l2_working_set.sh <sockshop|trainticket>}"
REPO="${REPO:-/scratch/yuvraj17/microservice-trace-dataset}"
DATASET_ROOT="${DATASET_ROOT:-/project/def-naser2/yuvraj17/microservice-trace-dataset}"
SRC="$DATASET_ROOT/$APP"
RUNS="${RUNS_ROOT:-/scratch/yuvraj17/agentic-runs}/$APP"     # where kernel_l2.jsonl lands
STAGE="${STAGE:-${SLURM_TMPDIR:-/scratch/yuvraj17/tmp_l2}/$APP}"   # node-local L0 staging
PAR="${PAR:-8}"
# babeltrace2 (local build) + big temp for prepare_ctf's gunzip (route OFF the small node /tmp)
export PATH="/scratch/yuvraj17/local/bin:$PATH"
export LD_LIBRARY_PATH="/scratch/yuvraj17/local/lib:${LD_LIBRARY_PATH:-}"
export STRATATRACE_APP="$APP"
export PYTHONPATH="$REPO/stratatrace:${PYTHONPATH:-}"
export TZ=UTC                       # ground_truth is UTC; babeltrace2 must window-match in UTC
MAXSEC="${MAXSEC:-0}"               # attribution window cap (s); 0 = full injection window
export TMPDIR="${TMPDIR:-${SLURM_TMPDIR:-/scratch/yuvraj17/tmp_l2}/bt}"; mkdir -p "$TMPDIR"
L2="$REPO/stratatrace/derive_kernel_l2.py"
UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
[ -d "$SRC" ] || { echo "FATAL: no archive dir $SRC"; exit 1; }
command -v babeltrace2 >/dev/null || { echo "FATAL: babeltrace2 not on PATH"; exit 1; }

derive_run() {  # $1 = staged run dir (has kernel/, meta/, ground_truth.json)
  local d="$1"; local rid rec out
  rid="$(basename "$d")"; rec="$(basename "$(dirname "$d")")"
  [ -f "$d/ground_truth.json" ] || { echo "SKIP $rid (no ground_truth)"; return; }
  out="$RUNS/$rec/$rid/kernel_l2.jsonl"
  [ -f "$out" ] && { echo "SKIP $rid (L2 exists)"; return; }
  local t0; t0=$(date +%s)
  if python3 "$L2" "$d" --max-seconds "$MAXSEC" > "$d/derive_l2.log" 2>&1 && [ -s "$d/kernel_l2.jsonl" ]; then
    mkdir -p "$RUNS/$rec/$rid"; cp "$d/kernel_l2.jsonl" "$out"
    echo "OK   $rid ($(( $(date +%s)-t0 ))s, $(wc -l < "$out") svc rows)"
  else
    echo "FAIL $rid ($(( $(date +%s)-t0 ))s; tail: $(tail -1 "$d/derive_l2.log" 2>/dev/null))"
  fi
  rm -rf "$d/kernel" 2>/dev/null   # free this run's L0 as soon as it's done
}
export -f derive_run; export RUNS L2 TMPDIR STRATATRACE_APP PYTHONPATH MAXSEC TZ

echo "== $APP L2 derive: SRC=$SRC -> $RUNS | PAR=$PAR | STAGE=$STAGE | TMPDIR=$TMPDIR =="
mapfile -t ARCHIVES < <(ls "$SRC"/*.tar.gz 2>/dev/null | grep -v '_aux_metrics_load.tar.gz')
for a in "${ARCHIVES[@]}"; do
  rec="$(basename "${a%.tar.gz}")"
  # already fully done? (every extracted run of this recipe has L2)
  need=$(ls -d "$RUNS/$rec"/*/ 2>/dev/null | wc -l)
  have=$(ls "$RUNS/$rec"/*/kernel_l2.jsonl 2>/dev/null | wc -l)
  if [ "$need" -gt 0 ] && [ "$need" = "$have" ]; then echo "== $rec: all $have have L2, skip =="; continue; fi
  echo "== $rec: staging L0+meta+gt ($(date +%H:%M:%S)) =="
  mkdir -p "$STAGE"
  $UNZ "$a" | tar --wildcards -xf - -C "$STAGE" \
      "$rec/*/kernel/*" "$rec/*/meta/*" "$rec/*/ground_truth.json" 2>/dev/null || true
  ls -d "$STAGE/$rec"/*/ 2>/dev/null | xargs -P "$PAR" -I{} bash -c 'derive_run "$@"' _ {}
  rm -rf "$STAGE/$rec"    # free the recipe's staged L0 before the next
done
tot=$(ls "$RUNS"/*/*/kernel_l2.jsonl 2>/dev/null | wc -l)
echo "== DONE $APP: $tot runs now have kernel_l2.jsonl =="
