#!/bin/bash
# Fault recipe: host-wide MEMORY pressure (stress-ng --bigheap). Fills the F3 gap.
# Bounded by a --memory-capped container so it drives reclaim / paging without
# hard-OOM-killing the collector or the stack. Named anomaly_mem to match
# anomaly_cpu + the existing verification_targets.json entry.
#
# Pre-registered expectation (fault_catalog.md F3): metrics detect (MemAvailable
# collapse); logs may show JVM GC storms / OOM; the KERNEL shows reclaim
# (mm_vmscan_*) + page-cache writeback (writeback_*) + allocation-stall waits.
#
# MECHANISM (wave-2 finding, 31-07): stress-ng --vm capped at ~7-8 GB on this VM
# regardless of workers/bytes/--vm-hang (it churns allocate/free rather than
# sustaining). We switched to **stress-ng --bigheap** (grows the heap via realloc
# and HOLDS it) run in a **--memory-capped container**: the cgroup cap bounds host
# RAM at the target (can't OOM-kill the stack), and hitting the cap triggers
# reclaim -> mm_vmscan_memcg_* (+ swap-out writeback_*) — the exact F3 signature.
# Needs the VM's 16 GB swap (added 31-07). --brk is a lighter alternative.
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
    # --bigheap grows the heap (realloc) and HOLDS it, run in a --memory-capped
    # container: the cgroup cap = target host RAM, so the container fills up to the
    # cap (dropping host MemAvailable) and hitting the cap forces reclaim
    # (mm_vmscan_memcg_*) + swap-out. Bounded by the cap -> cannot OOM-kill the
    # stack (unlike unbounded --vm/--brk). --memory-swap gives cgroup swap headroom
    # so overflow pages out (the VM's 16 GB swap) instead of cgroup-OOM-cycling.
    case "$INTENSITY" in
      subtle)     FRAC="${FRAC:-45}" ;;   # ~45% RAM
      aggressive) FRAC="${FRAC:-70}" ;;   # ~70% RAM -> MemAvailable collapse + active reclaim
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    WORKERS="${WORKERS:-2}"
    TOTAL_MB=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 ))
    CAP_MB=$(( TOTAL_MB * FRAC / 100 ))
    docker run -d --name "$CONTAINER" \
        --memory "${CAP_MB}m" --memory-swap "$(( CAP_MB + 8192 ))m" \
        "$STRESS_IMAGE" \
        stress-ng --bigheap "$WORKERS" > /dev/null
    gt_begin "$INTENSITY" "{\"stressor\": \"bigheap\", \"workers\": $WORKERS, \"mem_cap_mb\": $CAP_MB, \"target_frac_pct\": $FRAC, \"container\": \"$CONTAINER\"}"
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
