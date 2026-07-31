#!/bin/bash
# Fault recipe: host-wide DISK I/O saturation (stress-ng --hdd). Fills the F2
# gap (only host-CPU was collected in v1); one of the four confusable resource
# stressors RQ1 needs. Named anomaly_disk to match anomaly_cpu + the existing
# verification_targets.json entry.
#
# Pre-registered expectation (fault_catalog.md F2): metrics detect (node disk
# io_time -> 1); the KERNEL disambiguates - block_rq_* dominated by the stressor,
# DB threads in D-state (uninterruptible) waits.
#
# Containerized with a host bind-mount so writes hit the real block device ->
# block-layer kernel events. fsync (not O_DIRECT, which overlay may reject).
#
# Usage: ./anomaly_disk.sh inject [subtle|aggressive] | cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="anomaly_disk"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS='["host", "all services"]'
EXPECTED_WINNING_MODALITY="kernel"
TARGET_TRACE_VISIBILITY="n/a"
REMEDIATION="kill the stress-ng workers"

STRESS_IMAGE="${STRESS_IMAGE:-alexeiled/stress-ng:latest-ubuntu}"
CONTAINER="anomaly-disk-stress"
SCRATCH="${DISK_SCRATCH:-/var/tmp/anomaly-disk-stress}"

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
