#!/bin/bash
# Final assembly: manifest, per-app READMEs, the small "lite" bundle, checksums.
set -uo pipefail
D=/scratch/yuvraj17/stratatrace-v1

echo "== manifest + per-app READMEs =="
python3 /scratch/yuvraj17/reorg/build_manifest.py || exit 1

echo "== lite bundle =="
cp "$D/README.md" "$D/UNDERSTANDING-DATASET.md" "$D/manifest.csv" "$D/_lite/" 2>/dev/null
tar -I 'pigz -p 16' -cf "$D/stratatrace-lite.tar.gz.part" \
    -C "$D/_lite" --transform 's,^\./,stratatrace-lite/,' . || exit 1
mv "$D/stratatrace-lite.tar.gz.part" "$D/stratatrace-lite.tar.gz"
echo "   $(du -h "$D/stratatrace-lite.tar.gz" | cut -f1)"

echo "== checksums =="
( cd "$D" && find . -name '*.tar.gz' -printf '%P\n' | sort \
    | xargs -P 8 -I{} sh -c 'sha256sum "{}"' > CHECKSUMS.sha256.part \
    && sort -k2 CHECKSUMS.sha256.part > CHECKSUMS.sha256 && rm -f CHECKSUMS.sha256.part )
wc -l < "$D/CHECKSUMS.sha256" | xargs echo "   archives checksummed:"

echo "== final layout =="
du -sh "$D"/*.tar.gz "$D"/sockshop "$D"/trainticket 2>/dev/null
echo
echo "runs in manifest: $(( $(wc -l < "$D/manifest.csv") - 1 ))"
