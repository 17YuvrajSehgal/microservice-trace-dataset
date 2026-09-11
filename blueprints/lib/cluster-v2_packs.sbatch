#!/bin/bash
# Build evidence packs only - no decisions, no scoring.
#
# Used when adding runs for faults that have NO blueprint yet: there is nothing to decide with,
# and running the scorer would report zeroes that look like failures rather than absences.
#
#   sbatch blueprints/lib/cluster-v2_packs.sbatch <task_file>
#
# Packs land in the same directory as every other pack, so the derivation and scoring tools see
# one pool. Resumable: an existing pack is skipped.
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-v2-packs
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-v2-packs-%j.out
set -uo pipefail
REPO=/scratch/yuvraj17/stratatrace/repo
OUT=/scratch/yuvraj17/stratatrace/results/v2-blueprints-all
TASKS="${1:?usage: sbatch cluster-v2_packs.sbatch <task_file>}"
PAR="${PAR:-24}"
cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/packs"
export SLURM_TMPDIR="${SLURM_TMPDIR:-/tmp}"
N=$(grep -cvE '^[[:space:]]*(#|$)' "$TASKS")
echo "== packs start $(date -u +%FT%TZ) on $(hostname) | $N runs, $PAR at a time =="
build_one() {
  cd /scratch/yuvraj17/stratatrace/repo || return 1
  source transfer/env.sh >/dev/null 2>&1
  python blueprints/lib/v2_pack.py --app "$1" --family "$2" --run "$3" \
      --out /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
      --cache "${SLURM_TMPDIR:-/tmp}" ${FORCE:+--force}
}
# FORCE=1 rebuilds packs that already exist. Needed whenever a NEW measurement is added:
# the older packs predate it, and a signal missing from the NEGATIVES cannot be tested for
# separation at all - it would look as though the fault is the only family that has it,
# which is the most convincing kind of wrong answer.
export -f build_one
export FORCE
grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'build_one "$@"' _
echo "== done $(date -u +%FT%TZ) | packs now: $(ls "$OUT/packs"/*.json | wc -l) =="
