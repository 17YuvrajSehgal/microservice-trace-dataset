#!/bin/bash
# Rebuild every family archive as SELF-CONTAINED (adds L2 + metrics + load + RUN-INFO).
# Reads /project (never writes there); writes /scratch/yuvraj17/stratatrace-v1.
# Resumable: families already built are skipped.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-repack
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=08:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace-v1/_logs/repack-%j.out
set -uo pipefail

export STAGE_ROOT="${SLURM_TMPDIR:-/scratch/yuvraj17/reorg/stage}"
PAR="${PAR:-8}"          # families in flight
THREADS="${THREADS:-20}" # pigz threads per family
R=/scratch/yuvraj17/reorg
P=/project/def-naser2/yuvraj17/microservice-trace-dataset

echo "== repack start $(date -u +%FT%TZ)  PAR=$PAR THREADS=$THREADS STAGE=$STAGE_ROOT =="

# biggest first so the long poles start early
JOBS=$(for APP in sockshop trainticket; do
         for F in "$P/$APP"/*.tar.gz; do
           B=$(basename "$F" .tar.gz)
           [ "$B" = "_aux_metrics_load" ] && continue
           echo "$(stat -c %s "$F") $APP $B"
         done
       done | sort -rn | awk '{print $2","$3}')

echo "$JOBS" | tr ' ' '\n' | wc -l | xargs echo "families to process:"

printf '%s\n' $JOBS | xargs -P "$PAR" -I{} bash -c '
  IFS=, read -r APP FAM <<< "{}"
  bash '"$R"'/repack_family.sh "$APP" "$FAM" '"$THREADS"' >/dev/null 2>&1 \
    && echo "OK   $APP/$FAM" || echo "FAIL $APP/$FAM"
'

echo "== repack done $(date -u +%FT%TZ) =="
du -sh /scratch/yuvraj17/stratatrace-v1/* 2>/dev/null
