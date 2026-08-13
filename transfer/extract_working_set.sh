#!/bin/bash
# extract_working_set.sh — extract SMALL modalities (spans/logs/metrics/kernel L1-L3, NOT raw L0)
# from the /project compressed archives into a /scratch working tree the loader reads directly.
# Decompression is the cost (each .tar.gz is a stream → must be fully decompressed to reach the
# small files); we parallelize across recipes and only WRITE the small members.
#
#   bash extract_working_set.sh trainticket              # all runs of every recipe
#   RUNGLOB='*_r1' bash extract_working_set.sh sockshop  # one repeat per recipe/variant
#   PAR=6 bash extract_working_set.sh trainticket        # 6 archives decompressing at once
# Output: $RUNS_ROOT/<app>/<recipe>/<run>/...  + $RUNS_ROOT/<app>/<run>_metrics + <run>_load.csv
set -uo pipefail
APP="${1:?usage: extract_working_set.sh <sockshop|trainticket>}"
DATASET_ROOT="${DATASET_ROOT:-/project/def-naser2/yuvraj17/microservice-trace-dataset}"
SRC="${SRC:-$DATASET_ROOT/$APP}"
OUT="${OUT:-${RUNS_ROOT:-/scratch/yuvraj17/agentic-runs}/$APP}"
RUNGLOB="${RUNGLOB:-*}"
PAR="${PAR:-4}"
UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
mkdir -p "$OUT"
[ -d "$SRC" ] || { echo "FATAL: no archive dir $SRC"; exit 1; }

echo "== $APP: extract '$RUNGLOB' from $SRC -> $OUT (PAR=$PAR, $UNZ) =="
mapfile -t ARCHIVES < <(ls "$SRC"/*.tar.gz 2>/dev/null | grep -v '_aux_metrics_load.tar.gz')
[ "${#ARCHIVES[@]}" -gt 0 ] || { echo "FATAL: no recipe archives in $SRC"; exit 1; }

# One worker per recipe archive. The KEEP list + patterns are rebuilt inside each worker so the
# array is visible without exporting it; OUT and RUNGLOB are spliced in as literals.
printf '%s\n' "${ARCHIVES[@]}" | xargs -P "$PAR" -I{} bash -c '
  a="{}"; rec="$(basename "${a%.tar.gz}")"
  UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
  KEEP=( "/otlp/*" "/logs/*" "/meta/*" "/ground_truth.json" "/verification.json" \
         "/kernel_l1.parquet" "/kernel_l2.jsonl" "/kernel_l3.jsonl" \
         "/kernel/kernel_l1.parquet" "/kernel/kernel_l2.jsonl" "/kernel/kernel_l3.jsonl" )
  pats=(); for k in "${KEEP[@]}"; do pats+=( "${rec}/'"$RUNGLOB"'${k}" ); done
  t0=$(date +%s)
  $UNZ "$a" | tar --wildcards -xf - -C "'"$OUT"'" "${pats[@]}" 2>/dev/null
  n=$(ls -d "'"$OUT"'/$rec"/*/ 2>/dev/null | wc -l)
  echo "OK $rec ($(( $(date +%s)-t0 ))s, $n runs)"
'

# aux: per-run metrics dirs + load CSVs at the tree ROOT (loader resolves them as run siblings)
if [ -f "$SRC/_aux_metrics_load.tar.gz" ]; then
  echo "== aux metrics/load =="
  $UNZ "$SRC/_aux_metrics_load.tar.gz" | tar --wildcards -xf - -C "$OUT" \
      "${RUNGLOB}_metrics/*" "${RUNGLOB}_load.csv" 2>/dev/null || true
fi
runs=$(ls -d "$OUT"/*/*/ 2>/dev/null | wc -l)
echo "== DONE $APP: $runs runs under $OUT ($(du -sh "$OUT" 2>/dev/null | cut -f1)) =="
