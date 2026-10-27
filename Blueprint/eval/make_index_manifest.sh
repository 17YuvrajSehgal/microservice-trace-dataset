#!/bin/bash
# List every run dir the matched-blueprint eval needs an index for, one per line.
# Only runs whose index does NOT yet exist in the index root are emitted, so the
# sbatch array is sized to the real work. Login-node cheap (directory listings only).
set -euo pipefail
DATA=${DATA:-/scratch/yuvraj17/stratatrace/data/stratatrace-v2}
OUT=${OUT:-/scratch/yuvraj17/stratatrace/dataset/index-v2}
FAMILIES=${FAMILIES:-"svc_cpu_cap svc_mem_cap noisy_neighbor slow_db svc_net normal"}

for app in sockshop trainticket; do
  for fam in $FAMILIES; do
    for d in "$DATA/$app/$fam"/*/; do
      case "$d" in *_metrics/) continue;; esac
      rid=$(basename "$d")
      [ -e "$OUT/$rid.tsv.gz" ] && continue
      echo "${d%/}"
    done
  done
done
