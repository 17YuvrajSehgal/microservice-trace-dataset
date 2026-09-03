#!/bin/bash
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-verify
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/data/stratatrace-v1/_logs/verify-%j.out
set -uo pipefail
P=/project/def-naser2/yuvraj17/microservice-trace-dataset
echo "== verify start $(date -u +%FT%TZ) =="
for APP in sockshop trainticket; do
  for F in "$P/$APP"/*.tar.gz; do
    B=$(basename "$F" .tar.gz); [ "$B" = "_aux_metrics_load" ] && continue
    echo "$APP,$B"
  done
done | xargs -P 10 -I{} bash -c 'IFS=, read -r A F <<< "{}"; bash /scratch/yuvraj17/stratatrace/results/reorg/verify_family.sh "$A" "$F"'
echo "== verify done $(date -u +%FT%TZ) =="
