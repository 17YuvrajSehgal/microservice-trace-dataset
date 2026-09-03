#!/bin/bash
# Build ONE self-contained family archive. Reads only; never modifies the originals.
#   repack_family.sh <app> <family> [threads]
set -uo pipefail

APP="$1"; FAM="$2"; THREADS="${3:-8}"
SRC="/project/def-naser2/yuvraj17/microservice-trace-dataset/$APP/$FAM.tar.gz"
WS="/scratch/yuvraj17/stratatrace/data/agentic-runs/$APP"
DEST="/scratch/yuvraj17/stratatrace/data/stratatrace-v1"
OUT="$DEST/$APP"
LITE="$DEST/_lite/$APP/$FAM"
STAGE="${STAGE_ROOT:-/scratch/yuvraj17/stratatrace/results/reorg/stage}/$APP-$FAM"
LOG="$DEST/_logs/$APP-$FAM.log"

mkdir -p "$OUT" "$LITE" "$STAGE" "$DEST/_logs"
exec > >(tee -a "$LOG") 2>&1
echo "=== $APP/$FAM start $(date -u +%FT%TZ) ==="

[ -f "$SRC" ] || { echo "FAIL: no source archive $SRC"; exit 1; }

# skip if already built (resumable)
if [ -f "$OUT/$FAM.tar.gz" ] && [ -f "$OUT/$FAM.tar.gz.sha256" ]; then
    echo "already built, skipping"; rm -rf "$STAGE"; exit 0
fi

echo "-- extracting $(du -h "$SRC" | cut -f1) ..."
rm -rf "${STAGE:?}"/*
tar xzf "$SRC" -C "$STAGE" || { echo "FAIL: extract"; exit 1; }

ROOT="$STAGE/$FAM"
[ -d "$ROOT" ] || ROOT="$STAGE"          # some archives may not nest under the family name
N_IN=$(find "$ROOT" -mindepth 1 -maxdepth 1 -type d | wc -l)
echo "-- $N_IN run dirs extracted"

echo "-- enriching runs (L2 + metrics + load + RUN-INFO) ..."
for RD in "$ROOT"/*/; do
    [ -d "$RD" ] || continue
    python3 /scratch/yuvraj17/stratatrace/results/reorg/enrich_run.py "$RD" "$WS" "$FAM" "$LITE" || echo "  WARN enrich failed: $RD"
done

echo "-- repacking with pigz -p $THREADS ..."
tar -I "pigz -p $THREADS" -cf "$OUT/$FAM.tar.gz.part" -C "$(dirname "$ROOT")" "$(basename "$ROOT")" \
    || { echo "FAIL: repack"; exit 1; }
mv "$OUT/$FAM.tar.gz.part" "$OUT/$FAM.tar.gz"

echo "-- verifying archive is readable and complete ..."
N_OUT=$(tar tzf "$OUT/$FAM.tar.gz" | awk -F/ '{print $2}' | grep -v '^$' | sort -u | wc -l)
if [ "$N_OUT" -ne "$N_IN" ]; then echo "FAIL: run count $N_OUT != $N_IN"; exit 1; fi
L2=$(tar tzf "$OUT/$FAM.tar.gz" | grep -c 'kernel_l2.jsonl$')
MET=$(tar tzf "$OUT/$FAM.tar.gz" | grep -c '/metrics/$')
echo "   runs=$N_OUT  with_L2=$L2  with_metrics=$MET  size=$(du -h "$OUT/$FAM.tar.gz" | cut -f1)"

( cd "$OUT" && sha256sum "$FAM.tar.gz" > "$FAM.tar.gz.sha256" )
rm -rf "$STAGE"
echo "=== $APP/$FAM done $(date -u +%FT%TZ) ==="
