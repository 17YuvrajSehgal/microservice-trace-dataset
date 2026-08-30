#!/bin/bash
# Measure endpoint behaviour across the whole datastore-confusion set, both applications.
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
#SBATCH --job-name=bp-endpoints
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/bp-endpoints-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/microservice-trace-dataset
OUT=/scratch/yuvraj17/endpoints
TASKS="${1:-$REPO/blueprints/lib/tasks-endpoints.txt}"
PAR="${PAR:-6}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/logs"

echo "== endpoint sweep start $(date -u +%FT%TZ) =="
echo "tasks: $TASKS  ($(grep -cvE '^[[:space:]]*(#|$)' "$TASKS") runs, $PAR at a time)"

one() {
  APP="$1"; FAM="$2"; RUN="$3"
  REPO=/scratch/yuvraj17/microservice-trace-dataset
  OUT=/scratch/yuvraj17/endpoints
  L0=/scratch/yuvraj17/l0/$APP/$RUN
  cd "$REPO" || return 1
  source transfer/env.sh >/dev/null 2>&1

  {
    echo "--- $RUN ($APP/$FAM) $(date -u +%FT%TZ)"
    [ -d "$L0/ctf" ] || bash /scratch/yuvraj17/extract_l0.sh "$APP" "$FAM" "$RUN"
    [ -f "$L0/ground_truth.json" ] || \
      python blueprints/lib/synthesize_gt.py --ctf "$L0/ctf" --out "$L0/ground_truth.json"
    [ -f "$OUT/$RUN.json" ] || \
      python blueprints/lib/endpoint_latency.py --ctf "$L0/ctf" --gt "$L0/ground_truth.json" \
        --out "$OUT/$RUN.json"
  } >> "$OUT/logs/$RUN.log" 2>&1

  python - "$OUT/$RUN.json" "$FAM" <<'PY' 2>/dev/null || echo "  $RUN  NO RESULT"
import json, sys, os
try:
    s = json.load(open(sys.argv[1]))["signature"]
except Exception:
    print(f"  {os.path.basename(sys.argv[1])[:-5]:40s} NO RESULT"); raise SystemExit
print(f"  {os.path.basename(sys.argv[1])[:-5]:42s} {sys.argv[2]:18s} "
      f"slow={s['n_slowed_2x']}/{s['n_endpoints']} tail={s['median_tail_ratio_of_slowed']} "
      f"hung={s['n_hung']} gone={s['n_gone']} minresp={s['worst_response_ratio']}")
PY
}
export -f one

grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'one "$@"' _

echo
echo "== endpoint sweep done $(date -u +%FT%TZ) =="
python "$REPO/blueprints/lib/endpoint_report.py" --dir "$OUT" --tasks "$TASKS" \
       --out "$OUT/endpoint_summary.json" || true
