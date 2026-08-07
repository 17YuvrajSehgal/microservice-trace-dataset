#!/bin/bash
# Fault recipe: host-wide CPU saturation (stress-ng), inject/cleanup form so
# run_scenario/run_campaign can drive it like the service faults. The classic
# host resource stressor from the prior 148GB release, now with ground-truth
# emission and a declared verification target (anomaly_cpu).
#
# Pre-registered expectation (fault_catalog.md): metrics DETECT it cheaply
# (host CPU alarm) but the KERNEL disambiguates cause - stress-ng procnames
# dominating sched_switch while services sit runnable-but-waiting.
#
# Usage:
#   ./anomaly_cpu.sh inject [subtle|aggressive]
#   ./anomaly_cpu.sh cleanup
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="anomaly_cpu"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"all services\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-n/a}"
REMEDIATION="kill the stress-ng workers"

STRESS_IMAGE="${STRESS_IMAGE:-alexeiled/stress-ng:latest-ubuntu}"
CONTAINER="anomaly-cpu-stress"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    NCPU=$(nproc)
    case "$INTENSITY" in
      # aggressive: 2x cores fully loaded (cache thrash). subtle: half the
      # cores at ~50% load (a milder, harder-to-spot pressure).
      subtle)     WORKERS="${WORKERS:-$((NCPU / 2))}" LOAD="${LOAD:-50}" ;;
      aggressive) WORKERS="${WORKERS:-$((NCPU * 2))}" LOAD="${LOAD:-100}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # No --cpus cap: this is a HOST-wide stressor by design.
    docker run -d --name "$CONTAINER" "$STRESS_IMAGE" \
        stress-ng --cpu "$WORKERS" --cpu-method matrixprod --cpu-load "$LOAD" > /dev/null
    gt_begin "$INTENSITY" "{\"workers\": $WORKERS, \"cpu_load\": $LOAD, \"method\": \"matrixprod\", \"container\": \"$CONTAINER\"}"
    ;;
  cleanup)
    docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
    gt_end
    ;;
  status)
    docker ps --filter "name=$CONTAINER" --format '{{.Names}} {{.Status}}'
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
