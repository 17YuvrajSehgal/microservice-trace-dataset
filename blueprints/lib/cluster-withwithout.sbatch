#!/bin/bash
# THE WITH/WITHOUT EXPERIMENT.
#
# The question the supervisor asked in the 2026-08-26 meeting and that we have never
# measured: does having a blueprint beat not having one?
#
# Same model, same evidence pack, same incidents. ONE difference: the blueprint.
#
#   without   model + evidence + deterministic brief
#   with      model + evidence + deterministic brief + the 6 blueprints
#
# Two things keep this honest, both already built into the harness:
#   * --brief is on for BOTH arms, so "without" is the strong control that already tied the
#     full tool agent in earlier work, not a strawman.
#   * the skill selector sees ONLY the masked evidence survey. Nothing states the problem,
#     and `covers:` is harness metadata that never reaches the model.
#
# The deterministic blueprint arm (rules, no model) is scored separately and sits alongside.
#
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-withwithout
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=08:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-withwithout-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
OUT=/scratch/yuvraj17/stratatrace/results/withwithout
SKILLS=$REPO/blueprints/skills-generated
PACKS=/scratch/yuvraj17/stratatrace/data/packs/allpacks

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
set -a; source .env; set +a
mkdir -p "$OUT/transcripts"
cd agentic-rca || exit 1

SS_FAMS=anomaly_cpu,anomaly_disk,anomaly_mem,anomaly_net,dependency_outage,error_storm,noisy_neighbor,queue_backlog,slow_db,svc_cpu_cap,svc_mem_cap,svc_net
TT_FAMS=anomaly_cpu,anomaly_mem,dependency_outage,noisy_neighbor,slow_db,svc_cpu_cap,svc_net

echo "== with/without start $(date -u +%FT%TZ) =="
echo "model: ${RCA_PROVIDER:-?}/${RCA_MODEL:-?}   skills: $(ls "$SKILLS"/*.md 2>/dev/null | wc -l) blueprints"

arm () {   # arm <name> <app> <families> <skill args...>
  local n="$1" app="$2" fams="$3"; shift 3
  if [ -s "$OUT/$n.json" ]; then echo "SKIP $n"; return 0; fi
  echo "RUN  $n"
  python evaluate.py --app "$app" --families "$fams" --grid full --brief \
      --l0-pack-dir "$PACKS/$app" \
      --out "$OUT/$n.json" --transcripts "$OUT/transcripts/$n" "$@" \
      >> "$OUT/$n.log" 2>&1 && echo "OK   $n" || echo "FAIL $n (see $OUT/$n.log)"
}

# four streams: app x arm. Each incident is one model call chain, so this is the only
# parallelism available without touching evaluate.py.
arm without_ss sockshop    "$SS_FAMS" --skills off &
arm with_ss    sockshop    "$SS_FAMS" --skills full --skills-dir "$SKILLS" &
arm without_tt trainticket "$TT_FAMS" --skills off &
arm with_tt    trainticket "$TT_FAMS" --skills full --skills-dir "$SKILLS" &
wait

echo
echo "== with/without done $(date -u +%FT%TZ) =="
python "$REPO/blueprints/lib/withwithout_report.py" --dir "$OUT" \
       --out "$OUT/withwithout.json" || true
