#!/bin/bash
# Fault recipe: host-wide MEMORY pressure (stress-ng --vm, single worker, uncapped).
# Fills the F3 gap. Named anomaly_mem to match anomaly_cpu + the existing
# verification_targets.json entry.
#
# Pre-registered expectation (fault_catalog.md F3): metrics detect (MemAvailable
# collapse); logs may show JVM GC storms / OOM; the KERNEL shows reclaim
# (mm_vmscan_*) + page-cache writeback (writeback_*) + allocation-stall waits.
#
# MECHANISM (wave-2 finding, 31-07, calibrated on the VM):
#  - MULTI-worker --vm capped at ~7-8 GB (workers thrash/cycle) -> MemAvailable
#    barely moved. A SINGLE worker with absolute --vm-bytes + --vm-keep --vm-hang 0
#    HOLDS the full allocation (probed: 34 GB held, avail 35->7 GB, swap->6 GB).
#  - --bigheap in a --memory-CAPPED container passed the MemAvailable gate but the
#    memcg cap CONTAINED reclaim (OOM-killed the worker inside the cgroup; oom_ x2)
#    so host-global kswapd never ran -> ZERO mm_vmscan_ (the kernel signature was
#    LOST). So we run UNCAPPED and size the allocation to overshoot physical RAM
#    into swap: that forces global reclaim (mm_vmscan_*) AND drops MemAvailable,
#    while the 16 GB swap (added 31-07) keeps it OOM-safe (alloc+stack < RAM+swap).
#
# NOTE: the memory-management kernel signature is only captured with KERNEL_MEM=1
# (collect_trace.sh) - run_scenario/collect_wave2 set this for memory faults.
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
    # UNCAPPED single-worker --vm: one worker mmaps the full target, --vm-keep
    # holds the mapping and --vm-hang 0 sleeps on it (no free/re-alloc churn), so
    # the whole allocation stays resident. Sized as a % of RAM so alloc+stack
    # overshoots physical into the 16 GB swap -> host-global reclaim (mm_vmscan_*)
    # AND MemAvailable collapse, while staying under RAM+swap (OOM-safe). NO
    # --memory cap: a cgroup cap contains reclaim in the memcg and kills the
    # global kernel signature (the wave-2 finding).
    case "$INTENSITY" in
      subtle)     FRAC="${FRAC:-72}" ;;   # ~72% RAM held (near the gate; RQ5 variant)
      aggressive) FRAC="${FRAC:-88}" ;;   # ~88% RAM -> avail ~0.15 + swap-out reclaim
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    TOTAL_MB=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 ))
    VM_MB=$(( TOTAL_MB * FRAC / 100 ))
    docker run -d --name "$CONTAINER" "$STRESS_IMAGE" \
        stress-ng --vm 1 --vm-bytes "${VM_MB}m" --vm-keep --vm-hang 0 --page-in > /dev/null
    gt_begin "$INTENSITY" "{\"stressor\": \"vm-hang(single,uncapped)\", \"vm_bytes_mb\": $VM_MB, \"target_frac_pct\": $FRAC, \"container\": \"$CONTAINER\"}"
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
