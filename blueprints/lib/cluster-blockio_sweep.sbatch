#!/bin/bash
# Disk blueprint evidence: block-layer behaviour across EVERY fault family, both apps.
#
# The datastore rule owns 11 of the 13 remaining errors because it can see THAT a process is
# blocked on a socket but not WHAT it is blocked on. This produces the evidence for the two
# blueprints that fix it - service-network-path (A3) and frozen-dependency (A4) - and it
# covers every family that currently gets mistaken for a slow datastore, plus the no-fault
# control, so the discriminators are checked against each other rather than in isolation.
#
#   sbatch blueprints/lib/cluster-endpoint_sweep.sbatch <task_file>
#   task lines:  <app> <family> <run_id>
#
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-blockio
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-blockio-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
OUT=/scratch/yuvraj17/stratatrace/results/blockio
TASKS="${1:-$REPO/blueprints/lib/tasks-blockio.txt}"
PAR="${PAR:-6}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/logs"

echo "== blockio sweep start $(date -u +%FT%TZ) =="
echo "tasks: $TASKS  ($(grep -cvE '^[[:space:]]*(#|$)' "$TASKS") runs, $PAR at a time)"

one() {
  APP="$1"; FAM="$2"; RUN="$3"
  REPO=/scratch/yuvraj17/stratatrace/repo
  OUT=/scratch/yuvraj17/stratatrace/results/blockio
  L0=/scratch/yuvraj17/stratatrace/data/l0/$APP/$RUN
  cd "$REPO" || return 1
  source transfer/env.sh >/dev/null 2>&1

  {
    echo "--- $RUN ($APP/$FAM) $(date -u +%FT%TZ)"
    [ -d "$L0/ctf" ] || bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh "$APP" "$FAM" "$RUN"
    [ -f "$L0/ground_truth.json" ] || \
      python blueprints/lib/synthesize_gt.py --ctf "$L0/ctf" --out "$L0/ground_truth.json"
    [ -f "$OUT/$RUN.json" ] || \
      python blueprints/lib/block_io_signature.py --ctf "$L0/ctf" --gt "$L0/ground_truth.json" \
        --out "$OUT/$RUN.json"
  } >> "$OUT/logs/$RUN.log" 2>&1

  python - "$OUT/$RUN.json" "$FAM" <<'PY' 2>/dev/null || echo "  $RUN  NO RESULT"
import json, sys, os
try:
    s = json.load(open(sys.argv[1]))["signature"]
except Exception:
    print(f"  {os.path.basename(sys.argv[1])[:-5]:40s} NO RESULT"); raise SystemExit
print(f"  {os.path.basename(sys.argv[1])[:-5]:42s} {sys.argv[2]:18s} "
      f"newcomer={s['io_newcomer']} +{s['io_newcomer_iops_gained']}/s "
      f"iops={s['total_iops_x']}x devp95={s['worst_device_p95_x']}x "
      f"depth={s['queue_depth_x']}x")
PY
}
export -f one

grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'one "$@"' _

echo
echo "== blockio sweep done $(date -u +%FT%TZ) =="
python "$REPO/blueprints/lib/blockio_report.py" --dir "$OUT" --tasks "$TASKS" \
       --out "$OUT/blockio_summary.json" || true
