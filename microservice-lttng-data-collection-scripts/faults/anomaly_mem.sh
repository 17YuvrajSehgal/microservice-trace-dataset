#!/bin/bash
# Fault recipe: host-wide MEMORY pressure (stress-ng --vm). Fills the F3 gap.
# Bounded by --vm-bytes as a % of RAM so it drives reclaim / paging without
# hard-OOM-killing the collector or the stack. Named anomaly_mem to match
# anomaly_cpu + the existing verification_targets.json entry.
#
# Pre-registered expectation (fault_catalog.md F3): metrics detect (MemAvailable
# collapse); logs may show JVM GC storms / OOM; the KERNEL shows reclaim
# (mm_vmscan_*) + page-cache writeback (writeback_*) + allocation-stall waits.
#
# NOTE: the memory-management kernel signature is only captured with KERNEL_MEM=1
# (collect_trace.sh) - run_scenario/collect_wave2 set this for memory faults.
# INTENSITY is a CALIBRATION knob: aggressive aims ~80% RAM (reclaim active
# without OOM-killing lttng); Phase-1 calibration on the VM finalizes it.
#
# Usage: ./anomaly_mem.sh inject [subtle|aggressive] | cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="anomaly_mem"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS='["host", "all services"]'
EXPECTED_WINNING_MODALITY="kernel"
TARGET_TRACE_VISIBILITY="n/a"
REMEDIATION="kill the stress-ng workers"

STRESS_IMAGE="${STRESS_IMAGE:-alexeiled/stress-ng:latest-ubuntu}"
CONTAINER="anomaly-mem-stress"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    # Total resident pressure = WORKERS x PCT of RAM. Kept below 100% so the
    # stack degrades under reclaim/swap rather than being OOM-killed outright.
    case "$INTENSITY" in
      subtle)     WORKERS="${WORKERS:-2}" PCT="${PCT:-22%}" ;;   # ~44% RAM
      aggressive) WORKERS="${WORKERS:-3}" PCT="${PCT:-26%}" ;;   # ~78% RAM
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    docker run -d --name "$CONTAINER" "$STRESS_IMAGE" \
        stress-ng --vm "$WORKERS" --vm-bytes "$PCT" --vm-method all --vm-keep --page-in > /dev/null
    gt_begin "$INTENSITY" "{\"vm_workers\": $WORKERS, \"vm_bytes\": \"$PCT\", \"vm_keep\": true, \"container\": \"$CONTAINER\"}"
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
