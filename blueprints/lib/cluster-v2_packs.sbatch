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
#
# WALLTIME IS MEASURED, NOT GUESSED. A long request sits in the queue far longer than a
# short one, so over-asking costs wall-clock time even when the cluster is free. Measured on
# Trillium, one whole node, PAR=24:
#
#     156 packs (7 measurements each)      0:57:48
#     136 packs + decide + score           1:00:14
#     62 runs, on-CPU attribution only     0:20:37
#     extract 303 run bundles              0:18:39
#     decompress the whole tree            0:16:05
#     2-run smoke                          0:07:30
#
# That is about 7.4 min of work per run, divided by PAR. So:
#
#     walltime = runs * 7.4 min / PAR * 1.5   + 10 min
#
# The 1.5 covers a slower node and a busier filesystem; the 10 min covers startup and the
# report at the end. Earlier versions of these files asked for 6-8 hours for jobs that took
# under an hour, which is 6-22x over.
# This file: 156 runs at PAR=24 measured 0:57:48, so 1h30 with margin.
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-v2-packs
#SBATCH --nodes=1
#SBATCH --time=01:30:00
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
