#!/bin/bash
# Fault recipe: one service gets the lowest CPU weight while the host is busy (cgroup cpu.weight).
#
# A CPU weight is a share, not a limit: it changes nothing while cores are free. When every
# core is wanted, the scheduler divides them by weight, and a container with the lowest weight
# gets almost nothing. This is what a wrong "cpu shares" or a low-priority class in a
# deployment file does: fine in testing, starved in production when a neighbour gets busy.
#
# THIS RECIPE NEEDS A BUSY HOST FOR THE WHOLE RUN (baseline, injection and recovery alike), so
# the only thing that changes at injection is the weight. run_family.sh starts a neighbour
# container that keeps every core busy and records it in meta/load_setup.txt.
#
# WHY THIS FAMILY. svc_cpu_cap is a quota: the service is stopped for the rest of each 100 ms
# period, busy host or not. svc_cpuset removes cores. Here nothing is capped and no core is
# taken away: the service waits only because others are preferred, and it waits without any
# fixed period.
#
# Restart-free: one write to the container's cpu.weight on the host. Cleanup writes the old
# value back and reads it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS A2): the KERNEL shows the service's
# threads ready and waiting for a core for long, irregular times while the neighbour runs;
# METRICS show its answer time up; what users see is measured in the calibration.
#
# Usage:
#   TARGET_SVC=carts ./cpu_weight.sh inject [subtle|aggressive] | cleanup | status
#   env: WEIGHT (1-10000; the default of a container is 100)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="cpu_weight_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="give the container its normal CPU weight back (cpu.weight 100, or docker update --cpu-shares)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
CG="/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "$CONTAINER" 2>/dev/null).scope"
ORIG_FILE="$FAULT_STATE_DIR/${FAULT_NAME}.orig_weight"
weight() { cat "$CG/cpu.weight" 2>/dev/null | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) WEIGHT="${WEIGHT:-1}" ;;
      subtle)     WEIGHT="${WEIGHT:-10}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    BEFORE="$(weight)"
    [[ -n "$BEFORE" ]] || { echo "[$FAULT_NAME] cannot read cpu.weight of $CONTAINER"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"; echo "$BEFORE" > "$ORIG_FILE"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"cpu_weight\": $WEIGHT, \"cpu_weight_before\": $BEFORE, \"container\": \"$CONTAINER\"}"
    echo "$WEIGHT" | sudo tee "$CG/cpu.weight" > /dev/null
    echo "[$FAULT_NAME] cpu.weight $BEFORE -> $(weight)"
    ;;
  cleanup)
    ORIG="$(cat "$ORIG_FILE" 2>/dev/null || echo 100)"
    echo "$ORIG" | sudo tee "$CG/cpu.weight" > /dev/null
    NOW="$(weight)"
    [[ "$NOW" == "$ORIG" ]] || echo "[$FAULT_NAME] WARN: cpu.weight is '$NOW', wanted '$ORIG'"
    echo "[$FAULT_NAME] cpu.weight restored to $NOW"
    gt_end
    ;;
  status)
    echo "$CONTAINER cpu.weight=$(weight)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
