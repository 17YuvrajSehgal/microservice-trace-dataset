#!/bin/bash
# Decode each staged run ONCE into a shared evidence pack. 4 at a time.
set -uo pipefail
cd /scratch/yuvraj17/microservice-trace-dataset || exit 1
source transfer/env.sh >/dev/null 2>&1
OUT=/scratch/yuvraj17/evidence_packs
mkdir -p "$OUT"
ls -d /scratch/yuvraj17/l0/sockshop/*/ | while read -r D; do
  R=$(basename "$D")
  case "$R" in svc_cpu_cap*) continue ;; esac
  echo "$R"
done | xargs -P 4 -I{} bash -c '
  cd /scratch/yuvraj17/microservice-trace-dataset
  source transfer/env.sh >/dev/null 2>&1
  python blueprints/lib/l0_evidence.py --run-id "{}" --app sockshop --out '"$OUT"'
'
echo "== packs done $(date -u +%FT%TZ) =="
ls "$OUT"/*.json 2>/dev/null | wc -l
