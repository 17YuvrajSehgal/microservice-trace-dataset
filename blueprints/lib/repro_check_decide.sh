#!/bin/bash
# blueprint_decide is the verdict-relevant one, and it reads evidence packs rather than a
# trace, so we can check every pack cheaply. Two different hash seeds; verdicts must match.
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo || exit 1
V=/scratch/yuvraj17/stratatrace/results/repro/decide
mkdir -p "$V"
same=0; diffn=0; err=0
for p in /scratch/yuvraj17/stratatrace/data/packs/allpacks/sockshop/*.json /scratch/yuvraj17/stratatrace/data/packs/allpacks/trainticket/*.json; do
  n=$(basename "$p" .json)
  PYTHONHASHSEED=1 python3 blueprints/lib/blueprint_decide.py --pack "$p" --out "$V/${n}_h1.json" > /dev/null 2>&1
  PYTHONHASHSEED=2 python3 blueprints/lib/blueprint_decide.py --pack "$p" --out "$V/${n}_h2.json" > /dev/null 2>&1
  if [ ! -s "$V/${n}_h1.json" ] || [ ! -s "$V/${n}_h2.json" ]; then err=$((err+1)); continue; fi
  if diff -q "$V/${n}_h1.json" "$V/${n}_h2.json" > /dev/null; then
    same=$((same+1))
  else
    diffn=$((diffn+1)); echo "  VARIES: $n"; diff "$V/${n}_h1.json" "$V/${n}_h2.json" | head -6
  fi
done
echo
echo "blueprint_decide across two hash seeds: $same identical, $diffn varying, $err no-output"
