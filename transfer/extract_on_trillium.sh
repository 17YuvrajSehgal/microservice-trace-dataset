#!/bin/bash
# extract_on_trillium.sh — run ON Trillium/Nibi. Unpack the per-recipe .tar.gz archives into an
# organized run tree, WITHOUT touching the archives (tar -x only reads + writes new files; it never
# deletes or alters the .tar.gz), so the compressed copy stays as a cold backup you can re-extract.
#
# Extracts into a SEPARATE output dir (default: a sibling `extracted/`) so archives and the working
# copy don't intermix. Each <recipe>.tar.gz expands to <recipe>/<run>/... - archives never overlap
# (one fault family each), so nothing mixes.
#
#   cd /scratch/yuvraj17/stratatrace/repo/trainticket
#   bash extract_on_trillium.sh --list                 # inspect run counts, extract nothing
#   bash extract_on_trillium.sh                         # -> ./extracted/<recipe>/<run>/...
#   OUT=$SLURM_TMPDIR/tt bash extract_on_trillium.sh    # extract to fast node-local scratch (HPC way)
set -uo pipefail
ARCHIVE_DIR="${ARCHIVE_DIR:-$PWD}"
OUT="${OUT:-$ARCHIVE_DIR/extracted}"
UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
cd "$ARCHIVE_DIR"
shopt -s nullglob
ARCHIVES=( *.tar.gz )
[ "${#ARCHIVES[@]}" -gt 0 ] || { echo "no *.tar.gz in $ARCHIVE_DIR"; exit 1; }

if [ "${1:-}" = "--list" ]; then
  echo "== $ARCHIVE_DIR: ${#ARCHIVES[@]} archives (nothing extracted) =="
  tot=0
  for a in "${ARCHIVES[@]}"; do
    [ "$a" = "_aux_metrics_load.tar.gz" ] && { echo "  $a (per-run metrics + load CSVs)"; continue; }
    n=$($UNZ "$a" | tar -tf - 2>/dev/null | grep -cE '/meta/runinfo_end.txt$' || true)
    echo "  $a -> $n runs"; tot=$((tot+n))
  done
  echo "  TOTAL: $tot runs across ${#ARCHIVES[@]} archives"; exit 0
fi

mkdir -p "$OUT"
echo "== extracting ${#ARCHIVES[@]} archives  $ARCHIVE_DIR  ->  $OUT   (archives left INTACT) =="
fail=0
for a in "${ARCHIVES[@]}"; do
  echo -n "  $a ... "
  if $UNZ "$a" | tar -xf - -C "$OUT"; then echo "ok"; else echo "FAILED"; fail=$((fail+1)); fi
done
runs=$(ls -d "$OUT"/*/*/meta/runinfo_end.txt 2>/dev/null | wc -l)
echo "== done: $runs runs extracted to $OUT, $fail archive(s) failed. Archives untouched in $ARCHIVE_DIR =="
echo "   (sanity: compare '$runs' against '--list' TOTAL above)"
