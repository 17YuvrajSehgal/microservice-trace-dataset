#!/bin/bash
# ALL SEVEN BLUEPRINTS against v2, kernel traces only.
#
# Three stages, in one job so the packs never have to be staged twice:
#   1. build a full evidence pack per run (v2_pack.py - one decode, seven measurements)
#   2. run blueprint_decide.py over each pack
#   3. score every blueprint against the family the run was collected into
#
#   sbatch blueprints/lib/cluster-v2_all.sbatch [task_file]
#
# The CTF cache goes to $SLURM_TMPDIR - node-local, fast, and it disappears with the job, which
# matters because it is several GB per run and 24 run at once.
#
# Resumable: a run whose pack exists is skipped. Stage 2 and 3 are cheap and always re-run, so
# a resubmit after a wall-clock timeout costs only the packs that were still missing.
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-v2-all
#SBATCH --nodes=1
#SBATCH --time=08:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-v2-all-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
OUT=/scratch/yuvraj17/stratatrace/results/v2-blueprints-all
TASKS="${1:-$REPO/blueprints/lib/tasks-v2-latency.txt}"
PAR="${PAR:-24}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/packs" "$OUT/verdicts"
export SLURM_TMPDIR="${SLURM_TMPDIR:-/tmp}"

N=$(grep -cvE '^[[:space:]]*(#|$)' "$TASKS")
echo "== all blueprints on v2: start $(date -u +%FT%TZ) on $(hostname), $(nproc) cores =="
echo "   tasks $TASKS ($N runs, $PAR at a time)   tmp $SLURM_TMPDIR"
echo

# ---------------------------------------------------------------- 1. packs -------------------
build_one() {
  APP="$1"; FAM="$2"; RUN="$3"
  cd /scratch/yuvraj17/stratatrace/repo || return 1
  source transfer/env.sh >/dev/null 2>&1
  python blueprints/lib/v2_pack.py --app "$APP" --family "$FAM" --run "$RUN" \
      --out /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
      --cache "${SLURM_TMPDIR:-/tmp}"
}
export -f build_one

echo "-- stage 1: evidence packs --"
grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'build_one "$@"' _
echo "   packs: $(ls "$OUT/packs"/*.json 2>/dev/null | wc -l)/$N"

# ---------------------------------------------------------------- 2. verdicts ----------------
echo
echo "-- stage 2: blueprint decisions --"
for p in "$OUT/packs"/*.json; do
  r=$(basename "$p" .json)
  python blueprints/lib/blueprint_decide.py --pack "$p" --out "$OUT/verdicts/$r.json" \
      >/dev/null 2>&1 || echo "   decide failed: $r"
done
echo "   verdicts: $(ls "$OUT/verdicts"/*.json 2>/dev/null | wc -l)"

# ---------------------------------------------------------------- 3. score -------------------
echo
echo "-- stage 3: scoring --"
python blueprints/lib/score_v2_verdicts.py --verdicts "$OUT/verdicts" \
    --tasks "$TASKS" --out "$OUT/scored_all.json"

echo
echo "== done $(date -u +%FT%TZ) =="
