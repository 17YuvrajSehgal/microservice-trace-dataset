#!/bin/bash
# CPU-cluster measurement: run the on-CPU attribution over every run in the CPU confusion
# set, so the three-way discriminators can be READ from data rather than assumed.
#
# Runqueue delay is raised in all of them (finding F2), so it cannot be the discriminator.
# This measures what else the scheduler stream contains: who gained CPU, who lost it, and
# whether the host still had headroom.
#
# L0 is already staged for every run here, so this is decode only — no extraction.
#
#   sbatch blueprints/lib/cluster-cpu_measure.sbatch <task_file>
#
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-cpucluster
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/yuvraj17/bp-cpucluster-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/microservice-trace-dataset
OUT=/scratch/yuvraj17/cpucluster
TASKS="${1:-$REPO/blueprints/lib/tasks-cpucluster.txt}"
PAR="${PAR:-4}"

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
mkdir -p "$OUT/oncpu" "$OUT/logs"

echo "== cpu cluster measurement start $(date -u +%FT%TZ) =="
echo "tasks: $TASKS  ($(grep -cvE '^[[:space:]]*(#|$)' "$TASKS") runs, $PAR at a time)"

measure_one() {
  APP="$1"; FAM="$2"; RUN="$3"
  REPO=/scratch/yuvraj17/microservice-trace-dataset
  OUT=/scratch/yuvraj17/cpucluster
  L0=/scratch/yuvraj17/l0/$APP/$RUN
  cd "$REPO" || return 1
  source transfer/env.sh >/dev/null 2>&1

  if [ ! -f "$OUT/oncpu/$RUN.json" ]; then
    if [ ! -d "$L0/ctf" ]; then
      echo "  $RUN  NOT STAGED"; return 1
    fi
    # no-fault runs carry no injection window; cut one so they can be judged too
    [ -f "$L0/ground_truth.json" ] || \
      python blueprints/lib/synthesize_gt.py --ctf "$L0/ctf" --out "$L0/ground_truth.json" \
        >> "$OUT/logs/$RUN.log" 2>&1

    python blueprints/problems/cpu-contention-co-tenant/scripts/oncpu_share.py \
      --ctf "$L0/ctf" --gt "$L0/ground_truth.json" --out "$OUT/oncpu/$RUN.json" \
      >> "$OUT/logs/$RUN.log" 2>&1 || { echo "  $RUN  MEASURE FAILED"; return 1; }
  fi

  python - "$OUT/oncpu/$RUN.json" "$FAM" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])).get("signature", {})
print(f"  {sys.argv[1].split('/')[-1][:-5]:40s} {sys.argv[2]:16s} "
      f"util {s.get('host_util_baseline')}->{s.get('host_util_incident')}  "
      f"thief={s.get('thief_comm')} +{s.get('thief_cores_gained')}  "
      f"loser={s.get('biggest_loser_comm')} {s.get('biggest_loser_cores')}")
PY
}
export -f measure_one

grep -vE '^[[:space:]]*(#|$)' "$TASKS" | xargs -P "$PAR" -L 1 bash -c 'measure_one "$@"' _

echo
echo "== done $(date -u +%FT%TZ) =="
python "$REPO/blueprints/lib/cpu_cluster_report.py" --oncpu "$OUT/oncpu" \
       --tasks "$TASKS" --out "$OUT/cpu_cluster.json" || true
