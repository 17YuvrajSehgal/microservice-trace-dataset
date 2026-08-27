#!/bin/bash
# Extract ONE run's L0 kernel trace from a release archive and stage it for babeltrace2.
#   extract_l0.sh <app> <family> <run_id>
set -uo pipefail
APP="$1"; FAM="$2"; RUN="$3"
SRC="/scratch/yuvraj17/stratatrace-v1/$APP/$FAM.tar.gz"
DEST="/scratch/yuvraj17/l0/$APP/$RUN"
[ -d "$DEST/ctf" ] && { echo "already staged: $DEST/ctf"; exit 0; }
mkdir -p "$DEST"
echo "extracting $RUN from $(basename "$SRC") ..."
tar xzf "$SRC" -C "$DEST" --strip-components=2 \
    "$FAM/$RUN/kernel" "$FAM/$RUN/meta" "$FAM/$RUN/ground_truth.json" 2>/dev/null
[ -d "$DEST/kernel/kernel" ] || { echo "FAIL: no kernel dir extracted"; exit 1; }
cp -r "$DEST/kernel/kernel" "$DEST/ctf"
gunzip -f "$DEST"/ctf/*.gz 2>/dev/null
echo "staged: $DEST/ctf  ($(du -sh "$DEST/ctf" | cut -f1))"
ls "$DEST/ctf" | head -3
