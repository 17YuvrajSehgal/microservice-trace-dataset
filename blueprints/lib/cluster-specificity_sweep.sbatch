#!/bin/bash
# E1 SPECIFICITY SWEEP — offer both blueprints runs they should DECLINE.
#
# Every evidence pack we had before this job came from one of the two families the
# blueprints fire on, so a false positive was structurally impossible. This job supplies
# the missing negative class: other fault families, and no-fault runs.
#
# Per run: stage L0 -> (synthesise a window if the run has no fault) -> decode a
# kernel-only evidence pack -> apply both blueprints' decision rules -> record the verdict
# WITH its measured statistics, so thresholds can be re-examined without decoding again.
#
#   sbatch blueprints/lib/cluster-specificity_sweep.sbatch <task_file>
#   task_file lines:  <app> <family> <run_id>
#
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-specificity
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-specificity-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
OUT=/scratch/yuvraj17/stratatrace/data/packs/specificity
TASKS="${1:-$OUT/tasks.txt}"
PAR="${PAR:-4}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/packs" "$OUT/verdicts" "$OUT/logs"

echo "== specificity sweep start $(date -u +%FT%TZ) =="
echo "tasks: $TASKS  ($(grep -cvE '^[[:space:]]*(#|$)' "$TASKS") runs, $PAR at a time)"

run_one() {
  APP="$1"; FAM="$2"; RUN="$3"
  REPO=/scratch/yuvraj17/stratatrace/repo
  OUT=/scratch/yuvraj17/stratatrace/data/packs/specificity
  LOG="$OUT/logs/$RUN.log"
  cd "$REPO" || return 1
  source transfer/env.sh >/dev/null 2>&1

  {
    echo "--- $RUN ($APP/$FAM) start $(date -u +%FT%TZ)"
    if [ ! -f "$OUT/packs/$RUN.json" ]; then
      bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh "$APP" "$FAM" "$RUN" || { echo "EXTRACT FAILED"; return 1; }

      # A no-fault run carries no injection window. Cut one arbitrarily: the correct
      # outcome is still that nothing fires.
      GT="/scratch/yuvraj17/stratatrace/data/l0/$APP/$RUN/ground_truth.json"
      if [ ! -f "$GT" ]; then
        python blueprints/lib/synthesize_gt.py \
          --ctf "/scratch/yuvraj17/stratatrace/data/l0/$APP/$RUN/ctf" --out "$GT" || { echo "GT FAILED"; return 1; }
      fi

      python blueprints/lib/l0_evidence.py --run-id "$RUN" --app "$APP" \
        --kernel-only --out "$OUT/packs" || { echo "PACK FAILED"; return 1; }
    else
      echo "pack exists, skipping decode"
    fi

    python blueprints/lib/blueprint_decide.py \
      --pack "$OUT/packs/$RUN.json" --out "$OUT/verdicts/$RUN.json" || echo "DECIDE FAILED"
    echo "--- $RUN done $(date -u +%FT%TZ)"
  } >> "$LOG" 2>&1

  # one line to the job log so progress is visible without opening per-run files
  python - "$OUT/verdicts/$RUN.json" "$FAM" <<'PY' 2>/dev/null || echo "  $RUN  NO VERDICT"
import json, sys
try:
    v = json.load(open(sys.argv[1]))
except Exception:
    print(f"  {sys.argv[1]}  NO VERDICT"); raise SystemExit
sel = v.get("selected")
mark = "FIRED" if sel else "quiet"
print(f"  {v['run_id']:44s} truth={sys.argv[2]:20s} {mark:6s} {str(sel)}")
PY
}
export -f run_one

grep -vE '^\s*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'run_one "$@"' _

echo
echo "== sweep done $(date -u +%FT%TZ) =="
echo "packs:    $(ls "$OUT"/packs/*.json 2>/dev/null | wc -l)"
echo "verdicts: $(ls "$OUT"/verdicts/*.json 2>/dev/null | wc -l)"
python "$REPO/blueprints/lib/specificity_report.py" --verdicts "$OUT/verdicts" \
       --tasks "$TASKS" --out "$OUT/specificity.json" || true
