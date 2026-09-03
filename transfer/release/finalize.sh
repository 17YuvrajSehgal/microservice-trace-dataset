#!/bin/bash
# Final assembly: manifest, per-app READMEs, the small "lite" bundle, checksums.
set -uo pipefail
D=/scratch/yuvraj17/stratatrace/data/stratatrace-v1

echo "== manifest + per-app READMEs =="
python3 /scratch/yuvraj17/stratatrace/results/reorg/build_manifest.py || exit 1

echo "== lite bundle =="
cp "$D/README.md" "$D/UNDERSTANDING-DATASET.md" "$D/manifest.csv" "$D/_lite/" 2>/dev/null
tar -I 'pigz -p 16' -cf "$D/stratatrace-lite.tar.gz.part" \
    -C "$D" --transform 's,^_lite,stratatrace-lite,' _lite || exit 1
mv "$D/stratatrace-lite.tar.gz.part" "$D/stratatrace-lite.tar.gz"
echo "   size: $(du -h "$D/stratatrace-lite.tar.gz" | cut -f1)"
echo "   top entries:"; tar tzf "$D/stratatrace-lite.tar.gz" | head -3

echo "== checksums =="
cd "$D" || exit 1
find . -name '*.tar.gz' -printf '%P\n' | sort > /tmp/_arch.$$
xargs -a /tmp/_arch.$$ -P 8 -I{} sh -c 'sha256sum "{}"' | sort -k2 > CHECKSUMS.sha256
rm -f /tmp/_arch.$$
echo "   archives checksummed: $(wc -l < CHECKSUMS.sha256)"

echo "== final layout =="
du -sh "$D"/*.tar.gz "$D"/sockshop "$D"/trainticket 2>/dev/null
echo "runs in manifest: $(( $(wc -l < "$D/manifest.csv") - 1 ))"
