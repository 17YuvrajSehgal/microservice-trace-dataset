#!/bin/bash
# BLUEPRINT 1 (cpu-contention-co-tenant) against the v2 dataset.
#
# Re-measures the four-way CPU separation that the whole blueprint library rests on. The
# thresholds in blueprint_decide.py were read off 17 Sock Shop runs from v1:
#
#     host saturation   util 0.991-0.998   newcomer takes 6.54-6.62 cores
#     co-tenant         util 0.619-0.681   newcomer takes 0.99-2.00 cores
#     healthy           util 0.462-0.531   4/5 have no newcomer
#     cgroup cap        util 0.114-0.365   no newcomer, utilisation FALLS
#
# The blueprint's own stated limit is "one run per family so far". v2 answers that: the same
# four families, both applications, every repeat. If the bands hold, the thresholds are earned
# rather than fitted. If they overlap on Train Ticket, that is the more interesting result and
# it is better found now than in review.
#
#   sbatch blueprints/lib/cluster-v2_cpu.sbatch [task_file]
#
# Reads the v2 working copy directly - already extracted and decompressed, so no staging step.
# Resumable: a run whose oncpu json exists is skipped, so a job that hits the wall clock can be
# resubmitted and picks up where it stopped.
#SBATCH --account=def-naser2
#SBATCH --job-name=bp1-v2-cpu
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp1-v2-cpu-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
V2=/scratch/yuvraj17/stratatrace/data/stratatrace-v2
OUT=/scratch/yuvraj17/stratatrace/results/v2-blueprint1-cpu
TASKS="${1:-$REPO/blueprints/lib/tasks-v2-cpu.txt}"
# Whole-node scheduling gives us 192 cores. Each measurement is one babeltrace decode, which is
# a single stream, so parallelism comes from running many runs at once rather than from threads.
PAR="${PAR:-24}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/oncpu" "$OUT/logs"

N=$(grep -cvE '^[[:space:]]*(#|$)' "$TASKS")
echo "== blueprint 1 on v2: start $(date -u +%FT%TZ) on $(hostname), $(nproc) cores =="
echo "   tasks: $TASKS  ($N runs, $PAR at a time)"
echo "   out:   $OUT"
echo

measure_one() {
  APP="$1"; FAM="$2"; RUN="$3"
  REPO=/scratch/yuvraj17/stratatrace/repo
  V2=/scratch/yuvraj17/stratatrace/data/stratatrace-v2
  OUT=/scratch/yuvraj17/stratatrace/results/v2-blueprint1-cpu
  D="$V2/$APP/$FAM/$RUN"
  CTF="$D/kernel/kernel"
  cd "$REPO" || return 1
  source transfer/env.sh >/dev/null 2>&1

  if [ -f "$OUT/oncpu/$RUN.json" ]; then echo "  SKIP $RUN (measured)"; return 0; fi
  [ -d "$CTF" ] || { echo "  $RUN  NO CTF"; return 1; }

  # A no-fault run has no injection window, so there is nothing to cut a baseline against.
  # synthesize_gt.py cuts one from the trace's own span, which is what makes `normal` usable as
  # a control rather than merely unmeasured.
  GT="$D/ground_truth.json"
  if [ ! -f "$GT" ]; then
    GT="$OUT/oncpu/$RUN.gt.json"
    [ -f "$GT" ] || python blueprints/lib/synthesize_gt.py --ctf "$CTF" --out "$GT" \
        >> "$OUT/logs/$RUN.log" 2>&1
  fi

  python blueprints/problems/cpu-contention-co-tenant/scripts/oncpu_share.py \
    --ctf "$CTF" --gt "$GT" --out "$OUT/oncpu/$RUN.json" \
    >> "$OUT/logs/$RUN.log" 2>&1 || { echo "  $RUN  MEASURE FAILED (see logs/$RUN.log)"; return 1; }

  python - "$OUT/oncpu/$RUN.json" "$APP" "$FAM" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])).get("signature", {})
run = sys.argv[1].split('/')[-1][:-5]
print(f"  {run:46s} {sys.argv[2][:2]} {sys.argv[3]:16s} "
      f"util {s.get('host_util_baseline')}->{s.get('host_util_incident')}  "
      f"thief={s.get('thief_comm')} +{s.get('thief_cores_gained')}  "
      f"loser={s.get('biggest_loser_comm')} {s.get('biggest_loser_cores')}", flush=True)
PY
}
export -f measure_one

grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'measure_one "$@"' _

echo
echo "== measured $(ls "$OUT/oncpu"/*.json 2>/dev/null | grep -vc '\.gt\.json' || echo 0)/$N =="
python "$REPO/blueprints/lib/cpu_cluster_report.py" --oncpu "$OUT/oncpu" \
       --tasks "$TASKS" --out "$OUT/cpu_cluster_v2.json" || true
echo "== done $(date -u +%FT%TZ) =="
