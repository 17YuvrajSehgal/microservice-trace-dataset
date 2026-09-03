#!/bin/bash
# fetch_dev_sample.sh — build a SMALL local dev sample from the per-recipe archives on Trillium.
#
# Why: the agentic RCA harness only reads the derived/app modalities — spans, logs, metrics,
# and the kernel ladder L1/L2/L3 (parquet + jsonl, a few MB/run). It does NOT need the raw
# kernel CTF (L0), which is ~62% of every bundle. So we SELECT only the small members out of
# each <recipe>.tar.gz (never extracting L0) and pack them into one tiny tarball to scp down.
#
# Run this ON TRILLIUM, once per app, from inside that app's archive dir:
#   cd /scratch/yuvraj17/stratatrace/repo/trainticket
#   bash fetch_dev_sample.sh --list                      # see recipes + run counts, extract nothing
#   bash fetch_dev_sample.sh                             # default: run *_r1 of every recipe
#   RUNGLOB='*_r1' bash fetch_dev_sample.sh              # same, explicit
#   RUNGLOB='*'    bash fetch_dev_sample.sh              # ALL runs (still small — no L0)
#   APP=trainticket OUT=$HOME/dev-sample bash fetch_dev_sample.sh
# Produces:  $HOME/dev-sample-<app>.tar.gz   (scp this down — see the tail of this script)
set -uo pipefail
ARCHIVE_DIR="${ARCHIVE_DIR:-$PWD}"
APP="${APP:-$(basename "$ARCHIVE_DIR")}"          # sockshop | trainticket (inferred from dir name)
RUNGLOB="${RUNGLOB:-*_r1}"                        # which runs per recipe (default: the r1 of each)
STAGE="${OUT:-$HOME/dev-sample-$APP}"             # staging tree (mirrors <recipe>/<run>/...)
TARBALL="${TARBALL:-$HOME/dev-sample-$APP.tar.gz}"
UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
cd "$ARCHIVE_DIR"
shopt -s nullglob
ARCHIVES=( *.tar.gz )
[ "${#ARCHIVES[@]}" -gt 0 ] || { echo "no *.tar.gz in $ARCHIVE_DIR"; exit 1; }

# The SMALL members we keep (everything the loader reads except raw CTF L0). Selecting members
# explicitly (not excluding) guarantees the big kernel channels are never even decompressed.
KEEP=(
  "*/otlp/*"                    # spans.jsonl (traces)
  "*/logs/*"                    # per-container logs
  "*/meta/*"                    # runinfo + clock anchors
  "*/ground_truth.json" "*/verification.json"
  "*/kernel_l1.parquet" "*/kernel_l2.jsonl" "*/kernel_l3.jsonl"     # ladder at run root
  "*/kernel/kernel_l1.parquet" "*/kernel/kernel_l2.jsonl" "*/kernel/kernel_l3.jsonl"  # fallback layout
)

if [ "${1:-}" = "--list" ]; then
  echo "== $ARCHIVE_DIR ($APP): ${#ARCHIVES[@]} archives =="
  for a in "${ARCHIVES[@]}"; do
    [ "$a" = "_aux_metrics_load.tar.gz" ] && { echo "  $a (metrics + load CSVs)"; continue; }
    n=$($UNZ "$a" | tar -tf - 2>/dev/null | grep -cE '/meta/runinfo_end.txt$' || true)
    echo "  ${a%.tar.gz}: $n runs (matching '$RUNGLOB' would be selected)"
  done
  echo "  --> set RUNGLOB to pick runs; default '$RUNGLOB' = one run per recipe"
  exit 0
fi

mkdir -p "$STAGE"
echo "== staging SMALL modalities (no L0) for '$RUNGLOB' into $STAGE =="
for a in "${ARCHIVES[@]}"; do
  [ "$a" = "_aux_metrics_load.tar.gz" ] && continue
  rec="${a%.tar.gz}"
  # build the per-recipe member patterns: <recipe>/<runglob>/<keep>
  pats=(); for k in "${KEEP[@]}"; do pats+=( "${rec}/${RUNGLOB}${k#\*}" ); done
  echo -n "  $rec ... "
  # --wildcards so the globs match across '/'; some patterns (e.g. absent kernel_l2, or the
  # fallback kernel/ layout) match nothing -> tar exits non-zero but still extracts what it found.
  $UNZ "$a" | tar --wildcards -xf - -C "$STAGE" "${pats[@]}" 2>/dev/null
  echo "ok"
done

# aux metrics + load CSVs for the same runs, staged at the tree ROOT so loader._sibling_dir finds them
if [ -f "_aux_metrics_load.tar.gz" ]; then
  echo -n "  _aux (metrics+load) ... "
  $UNZ "_aux_metrics_load.tar.gz" | tar --wildcards -xf - -C "$STAGE" \
      "${RUNGLOB}_metrics/*" "${RUNGLOB}_load.csv" 2>/dev/null || true
  echo "ok"
fi

n=$(find "$STAGE" -name ground_truth.json 2>/dev/null | wc -l)
sz=$(du -sh "$STAGE" 2>/dev/null | cut -f1)
echo "== staged $n runs, $sz. Packing -> $TARBALL =="
tar cf - -C "$(dirname "$STAGE")" "$(basename "$STAGE")" | ${UNZ%-dc*}gzip -c > "$TARBALL" 2>/dev/null \
  || tar czf "$TARBALL" -C "$(dirname "$STAGE")" "$(basename "$STAGE")"
echo "== DONE: $TARBALL ($(du -sh "$TARBALL" | cut -f1)) =="
echo
echo "   Download to your laptop (run FROM the laptop, PowerShell), MFA when prompted:"
echo "     scp -i \$HOME/.ssh/trillium yuvraj17@trillium.scinet.utoronto.ca:$TARBALL ."
echo "   then, in the repo:  tar xzf dev-sample-$APP.tar.gz -C agentic-rca/dev-runs/"
