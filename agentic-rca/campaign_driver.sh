#!/bin/bash
# v4 skill campaign (design: progress-notes/16-08-2026): 4 conditions x 23 gate incidents
# + r=3 repeats on the 5 flip-prone (incident, condition) pairs found by the variance audit.
#   s0  = skills off, no brief          (generic floor)
#   s0b = brief only                    (Context Builder contribution)
#   s1  = skills full + brief           (production shape; skill lift)
#   s2  = skills LOFO + brief           (never-seen-fault claim)
# Login-node pattern: one fresh python per incident (watchdog-safe), resumable (skip-if-exists).
cd /scratch/yuvraj17/microservice-trace-dataset
source transfer/env.sh >/dev/null
set -a; source .env; set +a
cd agentic-rca
TT="anomaly_cpu anomaly_disk anomaly_mem anomaly_net slow_db error_storm svc_cpu_cap svc_mem_cap dependency_outage noisy_neighbor svc_net"
SS="anomaly_cpu anomaly_disk anomaly_mem anomaly_net slow_db error_storm svc_cpu_cap svc_mem_cap dependency_outage queue_backlog noisy_neighbor svc_net"
D="${CAMPAIGN_DIR:-results/campaign}"    # override for re-runs, e.g. CAMPAIGN_DIR=results/campaign2

flags() {  # condition -> evaluate.py flags
  case "$1" in
    s0)  echo "" ;;
    s0b) echo "--brief" ;;
    s1)  echo "--skills full --brief" ;;
    s2)  echo "--skills lofo --brief" ;;
  esac
}

run1() {  # run1 <cond> <app> <family> <rep-suffix or empty>
  local c="$1" app="$2" fam="$3" rep="$4"
  local out="$D/$c/${app}_${fam}${rep}.json"
  [ -s "$out" ] && { echo "skip $c ${app}_${fam}${rep}"; return; }
  echo "=== $c ${app}_${fam}${rep} $(date +%T) ==="
  # shellcheck disable=SC2046
  python -u evaluate.py --app "$app" --families "$fam" --per-family 1 --method agent \
    --grid full $(flags "$c") --out "$out" --transcripts "$D/$c/transcripts${rep}"
}

for c in s0 s0b s1 s2; do
  for f in $TT; do run1 "$c" trainticket "$f" ""; done
  for f in $SS; do run1 "$c" sockshop  "$f" ""; done
  echo "PHASE_DONE_$c $(date +%T)"
done

# r=3 repeats on the flip-prone pairs (2 extra runs each; distinct out + transcripts dirs)
for rep in _r2 _r3; do
  run1 s1  trainticket slow_db           "$rep"
  run1 s1  trainticket dependency_outage "$rep"
  run1 s1  trainticket svc_cpu_cap       "$rep"
  run1 s2  trainticket dependency_outage "$rep"
  run1 s0b sockshop    svc_mem_cap       "$rep"
done
echo "CAMPAIGN_DONE $(date +%T)"
