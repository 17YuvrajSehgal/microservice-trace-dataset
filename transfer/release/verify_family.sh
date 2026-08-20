#!/bin/bash
# Prove the new archive is a SUPERSET of the old one: every original path still present.
#   verify_family.sh <app> <family>
set -uo pipefail
APP="$1"; FAM="$2"
OLD="/project/def-naser2/yuvraj17/microservice-trace-dataset/$APP/$FAM.tar.gz"
NEW="/scratch/yuvraj17/stratatrace-v1/$APP/$FAM.tar.gz"
V="/scratch/yuvraj17/stratatrace-v1/_verify"; mkdir -p "$V"

tar tzf "$OLD" | sed 's,/$,,' | grep -v '^$' | sort -u > "$V/$APP-$FAM.old"
tar tzf "$NEW" | sed 's,/$,,' | grep -v '^$' | sort -u > "$V/$APP-$FAM.new"

MISSING=$(comm -23 "$V/$APP-$FAM.old" "$V/$APP-$FAM.new" | wc -l)
ADDED=$(comm -13 "$V/$APP-$FAM.old" "$V/$APP-$FAM.new" | wc -l)
O=$(wc -l < "$V/$APP-$FAM.old"); N=$(wc -l < "$V/$APP-$FAM.new")

if [ "$MISSING" -eq 0 ]; then
    echo "PASS $APP/$FAM  old=$O new=$N added=$ADDED missing=0"
    rm -f "$V/$APP-$FAM.old" "$V/$APP-$FAM.new"
else
    echo "FAIL $APP/$FAM  old=$O new=$N added=$ADDED MISSING=$MISSING"
    comm -23 "$V/$APP-$FAM.old" "$V/$APP-$FAM.new" | head -20 > "$V/$APP-$FAM.missing.txt"
fi
