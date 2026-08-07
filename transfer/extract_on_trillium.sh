#!/bin/bash
# extract_on_trillium.sh — run ON Trillium (or Nibi) to unpack the per-recipe archives into the
# organized run tree. Each <recipe>.tar.gz extracts to <recipe>/<run>/... - archives never overlap
# (one recipe each), so nothing mixes. Idempotent-ish; use --list to inspect without extracting.
#
#   cd /scratch/yuvraj17/microservice-trace-dataset/trainticket && bash extract_on_trillium.sh
#   bash extract_on_trillium.sh --list        # just tar-list each archive's run count
set -uo pipefail
DIR="${DIR:-$PWD}"; cd "$DIR"
UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
shopt -s nullglob
ARCHIVES=( *.tar.gz )
[ "${#ARCHIVES[@]}" -gt 0 ] || { echo "no *.tar.gz in $DIR"; exit 1; }
echo "== $DIR: ${#ARCHIVES[@]} archives, decompressor='$UNZ' =="
for a in "${ARCHIVES[@]}"; do
  if [ "${1:-}" = "--list" ]; then
    n=$($UNZ "$a" | tar -tf - 2>/dev/null | grep -cE '/meta/runinfo_end.txt$' || true); echo "  $a -> $n runs"; continue
  fi
  echo "  extracting $a ..."; $UNZ "$a" | tar -xf - && echo "    done" || echo "    FAILED $a"
done
[ "${1:-}" = "--list" ] || echo "== extracted. Runs on disk: $(ls -d */*/meta/runinfo_end.txt 2>/dev/null | wc -l) =="
