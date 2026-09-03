#!/bin/bash
set -uo pipefail
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v1
python3 /scratch/yuvraj17/stratatrace/results/reorg/build_manifest.py || exit 1
cd "$D" || exit 1
cp README.md UNDERSTANDING-DATASET.md manifest.csv _lite/
cp sockshop/README.md    _lite/sockshop/README.md
cp trainticket/README.md _lite/trainticket/README.md
tar -I 'pigz -p 16' -cf stratatrace-lite.tar.gz.part -C "$D" --transform 's,^_lite,stratatrace-lite,' _lite || exit 1
mv stratatrace-lite.tar.gz.part stratatrace-lite.tar.gz
TMP=$(mktemp)
grep -v 'stratatrace-lite.tar.gz$' CHECKSUMS.sha256 > "$TMP" 2>/dev/null || true
sha256sum stratatrace-lite.tar.gz >> "$TMP"
sort -k2 "$TMP" > CHECKSUMS.sha256; rm -f "$TMP"
echo "lite: $(du -h stratatrace-lite.tar.gz | cut -f1)  checksums: $(wc -l < CHECKSUMS.sha256)"
head -3 sockshop/README.md | tail -1
head -3 trainticket/README.md | tail -1
