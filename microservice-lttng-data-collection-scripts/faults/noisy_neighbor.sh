#!/bin/bash
# Fault recipe: noisy neighbor (cgroup-capped co-located stress container).
#
# Launches a stress-ng container capped tightly enough that service KPIs
# barely move while kernel-level contention (runnable-wait, cache and
# scheduler pressure) is blatant. THE kernel-only showcase recipe: app-level
# modalities are near-blind by construction. Calibration of "barely move"
# happens on the VM against real KPIs (see vm-todo.md).
#
# Pre-registered expectations (see faults/README.md): KERNEL only. The
# neighbor emits no spans, no service logs, no service metrics; cadvisor
# shows a new container if the analyst thinks to look.
#
# Usage:
#   ./noisy_neighbor.sh inject [subtle|aggressive]
#   ./noisy_neighbor.sh cleanup
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="E_infrastructure"
FAULT_NAME="noisy_neighbor"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"all services (mild)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="remove the neighbor container"

STRESS_IMAGE="${STRESS_IMAGE:-alexeiled/stress-ng:latest-ubuntu}"
NEIGHBOR="noisy-neighbor"

case "${1:-}" in
  inject)
    INTENSITY="${2:-subtle}"
    case "$INTENSITY" in
      # Caps chosen so the neighbor contends for scheduler/cache without
      # starving services outright; VM calibration may tune these.
      subtle)     CPUS="${CPUS:-1.0}" WORKERS="${WORKERS:-2}" ;;
      aggressive) CPUS="${CPUS:-2.0}" WORKERS="${WORKERS:-4}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # The image has no entrypoint (Cmd=/bin/bash) - invoke stress-ng explicitly.
    docker run -d --name "$NEIGHBOR" --cpus="$CPUS" \
        "$STRESS_IMAGE" stress-ng --cpu "$WORKERS" --cpu-method matrixprod > /dev/null
    gt_begin "$INTENSITY" "{\"cpus_cap\": $CPUS, \"workers\": $WORKERS, \"image\": \"$STRESS_IMAGE\", \"container\": \"$NEIGHBOR\"}"
    ;;
  cleanup)
    docker rm -f "$NEIGHBOR" > /dev/null 2>&1 || true
    gt_end
    ;;
  status)
    docker ps --filter "name=$NEIGHBOR" --format '{{.Names}} {{.Status}}'
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
