#!/bin/bash
# Fault recipe: host-wide DISK I/O saturation (stress-ng --hdd), inject/cleanup
# form so run_scenario/run_campaign drive it like the other faults. Fills the
# F2 gap (only host-CPU was collected in v1); one of the four confusable
# resource stressors RQ1 needs.
#
# Pre-registered expectation (fault_catalog.md F2): metrics detect (node disk
# io_time -> 1); the KERNEL disambiguates - block_rq_* dominated by the stressor,
# DB threads in D-state (uninterruptible) waits.
#
# Containerized (like anomaly_cpu) with a host bind-mount so the writes hit the
# real block device -> block-layer kernel events. fsync (not O_DIRECT, which
# overlay may reject) for strong write-latency pressure.
#
# Usage: ./host_disk.sh inject [subtle|aggressive] | cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="host_disk"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS='["host", "all services"]'
EXPECTED_WINNING_MODALITY="kernel"
TARGET_TRACE_VISIBILITY="n/a"
REMEDIATION="kill the stress-ng workers"

STRESS_IMAGE="${STRESS_IMAGE:-alexeiled/stress-ng:latest-ubuntu}"
CONTAINER="host-disk-stress"
SCRATCH="${DISK_SCRATCH:-/var/tmp/host-disk-stress}"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    NCPU=$(nproc)
    case "$INTENSITY" in
      subtle)     WORKERS="${WORKERS:-$(( NCPU / 2 > 0 ? NCPU / 2 : 1 ))}" BYTES="${BYTES:-256M}" ;;
      aggressive) WORKERS="${WORKERS:-$NCPU}" BYTES="${BYTES:-1G}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    mkdir -p "$SCRATCH"
    docker run -d --name "$CONTAINER" -v "$SCRATCH":/stress "$STRESS_IMAGE" \
        stress-ng --hdd "$WORKERS" --hdd-bytes "$BYTES" --hdd-opts fsync \
                  --temp-path /stress > /dev/null
    gt_begin "$INTENSITY" "{\"hdd_workers\": $WORKERS, \"hdd_bytes\": \"$BYTES\", \"hdd_opts\": \"fsync\", \"scratch\": \"$SCRATCH\", \"container\": \"$CONTAINER\"}"
    ;;
  cleanup)
    docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
    rm -rf "$SCRATCH" 2>/dev/null || true
    gt_end
    ;;
  status)
    docker ps --filter "name=$CONTAINER" --format '{{.Names}} {{.Status}}'
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
