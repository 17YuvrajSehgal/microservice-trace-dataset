#!/bin/bash
# RE-TEST after the CPU cluster: add on-CPU evidence to every pack, then re-decide.
#
# The old rules decided the CPU family on runqueue delay and produced a 42-62% false-positive
# rate. The new rules decide on host CPU utilisation. This measures whether that helped, over
# the same runs, so the comparison is like for like.
#
# Handles both applications and both pack directories:
#   sockshop positives  /scratch/yuvraj17/stratatrace/data/packs/evidence_packs
#   sockshop negatives  /scratch/yuvraj17/stratatrace/data/packs/specificity/packs
#   trainticket         /scratch/yuvraj17/stratatrace/data/packs/evidence_packs_tt
#
#   sbatch blueprints/lib/cluster-retest.sbatch <task_file>
#   task lines:  <app> <family> <run_id> <pack_dir>
#
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-retest
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-retest-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
OUT=/scratch/yuvraj17/stratatrace/results/retest
TASKS="${1:-$REPO/blueprints/lib/tasks-retest.txt}"
PAR="${PAR:-8}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/verdicts" "$OUT/logs"

echo "== retest start $(date -u +%FT%TZ) =="
echo "tasks: $TASKS  ($(grep -cvE '^[[:space:]]*(#|$)' "$TASKS") runs, $PAR at a time)"

retest_one() {
  APP="$1"; FAM="$2"; RUN="$3"; PACKDIR="$4"
  REPO=/scratch/yuvraj17/stratatrace/repo
  OUT=/scratch/yuvraj17/stratatrace/results/retest
  cd "$REPO" || return 1
  source transfer/env.sh >/dev/null 2>&1

  {
    echo "--- $RUN ($APP/$FAM) $(date -u +%FT%TZ)"
    # stage the trace if this run has never been decoded before
    [ -d "/scratch/yuvraj17/stratatrace/data/l0/$APP/$RUN/ctf" ] || \
      bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh "$APP" "$FAM" "$RUN"
    # build the pack if it does not exist yet (train ticket negatives)
    [ -f "$PACKDIR/$RUN.json" ] || \
      python blueprints/lib/l0_evidence.py --run-id "$RUN" --app "$APP" \
        --kernel-only --out "$PACKDIR"
    python blueprints/lib/add_oncpu_to_pack.py --run-id "$RUN" --app "$APP" \
      --pack-dir "$PACKDIR"
  } >> "$OUT/logs/$RUN.log" 2>&1

  if [ -f "$PACKDIR/$RUN.json" ]; then
    python blueprints/lib/blueprint_decide.py --pack "$PACKDIR/$RUN.json" \
      --out "$OUT/verdicts/$RUN.json" >> "$OUT/logs/$RUN.log" 2>&1
  fi

  python - "$OUT/verdicts/$RUN.json" "$FAM" <<'PY' 2>/dev/null || echo "  $RUN  NO VERDICT"
import json, sys, os
try:
    v = json.load(open(sys.argv[1]))
except Exception:
    print(f"  {os.path.basename(sys.argv[1])[:-5]:44s} NO VERDICT"); raise SystemExit
sel = v.get("selected")
print(f"  {str(v['run_id']):44s} truth={sys.argv[2]:18s} "
      f"{'FIRED' if sel else 'quiet':6s} {str(sel)}")
PY
}
export -f retest_one

grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'retest_one "$@"' _

echo
echo "== retest done $(date -u +%FT%TZ) =="
python "$REPO/blueprints/lib/retest_report.py" --verdicts "$OUT/verdicts" \
       --tasks "$TASKS" --out "$OUT/retest.json" || true
