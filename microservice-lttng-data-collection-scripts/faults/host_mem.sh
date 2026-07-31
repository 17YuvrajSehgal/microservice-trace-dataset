#!/bin/bash
# Fault recipe: host-wide MEMORY pressure (stress-ng --vm), inject/cleanup form.
# Fills the F3 gap. Bounded by --vm-bytes as a % of RAM so it drives reclaim /
# paging without hard-OOM-killing the collector or the stack.
#
# Pre-registered expectation (fault_catalog.md F3): metrics detect (MemAvailable
# collapse); logs may show JVM GC storms / OOM; the KERNEL shows reclaim /
# pgfault / kswapd activity + allocation-stall waits.
#
# NOTE: the memory-management kernel signature is only captured when the trace
# session runs with KERNEL_MEM=1 (collect_trace.sh) - pair this fault with that.
#
# Usage: ./host_mem.sh inject [subtle|aggressive] | cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="host_mem"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS='["host", "all services"]'
EXPECTED_WINNING_MODALITY="kernel"
TARGET_TRACE_VISIBILITY="n/a"
REMEDIATION="kill the stress-ng workers"

STRESS_IMAGE="${STRESS_IMAGE:-alexeiled/stress-ng:latest-ubuntu}"
CONTAINER="host-mem-stress"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    # Total resident pressure = WORKERS x PCT of RAM. Kept below 100% so the
    # stack degrades under reclaim/swap rather than being OOM-killed outright.
    case "$INTENSITY" in
      subtle)     WORKERS="${WORKERS:-2}" PCT="${PCT:-22%}" ;;   # ~44% RAM
      aggressive) WORKERS="${WORKERS:-3}" PCT="${PCT:-25%}" ;;   # ~75% RAM
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
