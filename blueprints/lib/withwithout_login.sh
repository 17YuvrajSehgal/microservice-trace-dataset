#!/bin/bash
# THE WITH/WITHOUT EXPERIMENT — login-node driver.
#
# The question the supervisor asked on 2026-08-26 and that we had never measured: does having
# a blueprint beat not having one?
#
# Same model, same evidence pack, same incidents. ONE difference: the blueprint.
#
#   without   model + evidence + deterministic brief
#   with      model + evidence + deterministic brief + the 6 blueprints
#
# Two things keep it honest, both already in the harness:
#   * --brief is on for BOTH arms, so "without" is the strong control that already tied the
#     full tool agent in earlier work, not a strawman.
#   * the skill selector sees ONLY the masked evidence survey. Nothing states the problem, and
#     `covers:` is harness metadata that never reaches the model.
#
# WHY THIS IS NOT AN SBATCH JOB. It was, and every single incident returned "Request timed
# out." with 0 tool calls. Trillium COMPUTE NODES HAVE NO INTERNET, so the agent can never
# reach the LLM endpoint from a batch job. This was already measured and written down in
# agentic-rca/RESULTS-agent-sanitygate.md; the sbatch ignored it. Agent runs are login-node
# only.
#
# The login node then imposes its own constraint: a watchdog kills long cumulative processes
# (one incident is fine, 23 back-to-back got killed). So this follows the v4 campaign pattern -
# ONE FRESH PYTHON PER FAMILY, resumable by skip-if-exists. Four streams (arm x app) run
# concurrently; at ~7 GB each that is nothing against the login node's 755 GB.
#
#   nohup bash blueprints/lib/withwithout_login.sh > /scratch/yuvraj17/withwithout/driver.log 2>&1 &
set -uo pipefail

REPO=/scratch/yuvraj17/microservice-trace-dataset
OUT=/scratch/yuvraj17/withwithout
SKILLS=$REPO/blueprints/skills-generated
PACKS=/scratch/yuvraj17/allpacks
PER_FAMILY=${PER_FAMILY:-3}          # incidents per family per arm; keeps each python short

cd "$REPO" || exit 1
source transfer/env.sh >/dev/null 2>&1
set -a; source .env; set +a
cd agentic-rca || exit 1

SS_FAMS="anomaly_cpu anomaly_disk anomaly_mem anomaly_net dependency_outage error_storm noisy_neighbor queue_backlog slow_db svc_cpu_cap svc_mem_cap svc_net"
TT_FAMS="anomaly_cpu anomaly_mem dependency_outage noisy_neighbor slow_db svc_cpu_cap svc_net"

echo "== with/without start $(date -u +%FT%TZ) on $(hostname) =="
echo "model: ${RCA_PROVIDER:-?}/${RCA_MODEL:-?}   blueprints: $(ls "$SKILLS"/*.md 2>/dev/null | wc -l)   per-family: $PER_FAMILY"

chunk () {   # chunk <arm> <tag> <app> <family> <skill args...>
  local arm="$1" tag="$2" app="$3" fam="$4"; shift 4
  # two statements on purpose: bash expands ALL words of a `local` before assigning any, so
  # `local dir=... out="$dir/..."` reads dir while it is still unset (fatal under `set -u`).
  local dir="$OUT/${arm}_${tag}"
  local out="$dir/${fam}.json"
  mkdir -p "$dir"
  if [ -s "$out" ]; then echo "skip ${arm}_${tag} $fam"; return 0; fi
  echo "run  ${arm}_${tag} $fam $(date +%T)"
  python -u evaluate.py --app "$app" --families "$fam" --per-family "$PER_FAMILY" \
      --method agent --grid full --brief --l0-pack-dir "$PACKS/$app" \
      --out "$out" --transcripts "$dir/transcripts" "$@" \
      >> "$dir/$fam.log" 2>&1 \
    && echo "ok   ${arm}_${tag} $fam" \
    || echo "FAIL ${arm}_${tag} $fam (see $dir/$fam.log)"
}

stream () {  # stream <arm> <tag> <app> <families> <skill args...>
  local arm="$1" tag="$2" app="$3" fams="$4"; shift 4
  for f in $fams; do chunk "$arm" "$tag" "$app" "$f" "$@"; done
  echo "STREAM_DONE ${arm}_${tag} $(date +%T)"
}

stream without ss sockshop    "$SS_FAMS" --skills off &
stream with    ss sockshop    "$SS_FAMS" --skills full --skills-dir "$SKILLS" &
stream without tt trainticket "$TT_FAMS" --skills off &
stream with    tt trainticket "$TT_FAMS" --skills full --skills-dir "$SKILLS" &
wait

echo
echo "== merging $(date -u +%FT%TZ) =="
cd "$REPO" || exit 1
for a in without_ss with_ss without_tt with_tt; do
  python3 blueprints/lib/merge_chunks.py --glob "$OUT/$a/*.json" --out "$OUT/$a.json" || true
done

echo
python3 blueprints/lib/withwithout_report.py --dir "$OUT" --out "$OUT/withwithout.json" || true
echo "== with/without done $(date -u +%FT%TZ) =="
