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
    # Consume+HOLD a fraction of RAM. Key: --vm-hang 0 makes each worker touch its
    # pages then hang, keeping them resident (the default/--vm-method loop frees and
    # re-allocs, so it never sustains pressure - the wave-2 finding). Absolute
    # per-worker bytes computed from MemTotal (--vm-bytes % under-allocated here).
    # Needs the VM's 16 GB swap so overshoot reclaims to swap instead of hard-OOM.
    case "$INTENSITY" in
      subtle)     WORKERS="${WORKERS:-2}" FRAC="${FRAC:-40}" ;;   # ~40% RAM held
      aggressive) WORKERS="${WORKERS:-4}" FRAC="${FRAC:-72}" ;;   # ~72% RAM held -> reclaim/swap fires
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    TOTAL_MB=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 ))
    PERWORKER_MB=$(( TOTAL_MB * FRAC / 100 / WORKERS ))
    docker run -d --name "$CONTAINER" "$STRESS_IMAGE" \
        stress-ng --vm "$WORKERS" --vm-bytes "${PERWORKER_MB}m" --vm-hang 0 --vm-keep --page-in > /dev/null
    gt_begin "$INTENSITY" "{\"vm_workers\": $WORKERS, \"vm_bytes_mb_each\": $PERWORKER_MB, \"target_frac_pct\": $FRAC, \"mode\": \"vm-hang(hold)\", \"container\": \"$CONTAINER\"}"
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
