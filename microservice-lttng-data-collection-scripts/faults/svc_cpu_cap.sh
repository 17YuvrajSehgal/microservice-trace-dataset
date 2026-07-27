#!/bin/bash
# Fault recipe: service-targeted CPU throttle (cgroup quota via docker update).
#
# Caps one service's CPU without touching the host or other containers -
# the service-scoped counterpart of 1_cpu_stress.sh's host-wide saturation,
# making "which service?" RCA well-posed.
#
# Pre-registered expectations (see faults/README.md): app-level modalities
# see "service X is slow" (inflated spans, latency histograms); only the
# KERNEL shows the mechanism - cgroup throttling appears as runnable-but-
# not-running wait (sched_switch gaps) rather than on-CPU work.
#
# Usage:
#   TARGET_SVC=carts ./svc_cpu_cap.sh inject [subtle|aggressive]
#   TARGET_SVC=carts ./svc_cpu_cap.sh cleanup
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="svc_cpu_cap_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="[\"$TARGET_SVC\", \"front-end\"]"
EXPECTED_WINNING_MODALITY="kernel"
TARGET_TRACE_VISIBILITY="covered"
REMEDIATION="restore original cpu quota via docker update"

CONTAINER="$(resolve_container "$TARGET_SVC")"
ORIG_FILE="$FAULT_STATE_DIR/${FAULT_NAME}.orig_nanocpus"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     CPUS="${CPUS:-0.5}" ;;
      aggressive) CPUS="${CPUS:-0.2}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    mkdir -p "$FAULT_STATE_DIR"
    # Capture BOTH representations: docker leaves NanoCpus stale after a
    # quota-based reset, so neither field alone is trustworthy.
    docker inspect -f '{{.HostConfig.NanoCpus}} {{.HostConfig.CpuQuota}}' "$CONTAINER" > "$ORIG_FILE"
    docker update --cpus="$CPUS" "$CONTAINER" > /dev/null
    gt_begin "$INTENSITY" "{\"cpus\": $CPUS, \"container\": \"$CONTAINER\", \"orig_nanocpus_quota\": \"$(cat "$ORIG_FILE")\"}"
    ;;
  cleanup)
    read -r ORIG_NANO ORIG_QUOTA < "$ORIG_FILE" 2>/dev/null || { ORIG_NANO=0; ORIG_QUOTA=0; }
    # `docker update --cpus=0` is a silent no-op ("0 = no change" in the
    # API); the reset that actually clears the cgroup quota (verified
    # against /sys/fs/cgroup/cpu.max) is a -1 cfs quota.
    if [[ "$ORIG_QUOTA" == "-1" ]]; then
      docker update --cpu-quota=-1 "$CONTAINER" > /dev/null
    elif [[ "$ORIG_NANO" -gt 0 ]]; then
      docker update --cpus="$(awk "BEGIN{print $ORIG_NANO/1000000000}")" "$CONTAINER" > /dev/null
    elif [[ "$ORIG_QUOTA" -gt 0 ]]; then
      docker update --cpu-quota="$ORIG_QUOTA" "$CONTAINER" > /dev/null
    else
      docker update --cpu-quota=-1 "$CONTAINER" > /dev/null
    fi
    gt_end
    ;;
  status)
    docker inspect -f '{{.Name}} NanoCpus={{.HostConfig.NanoCpus}}' "$CONTAINER"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
