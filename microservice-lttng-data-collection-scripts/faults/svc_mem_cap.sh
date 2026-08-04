#!/bin/bash
# Fault recipe: service-targeted memory cap (cgroup limit via docker update).
#
# Caps one service's memory. On the JVM services (Xmx256m) the aggressive
# cap sits below the heap ceiling -> mounting GC pressure and eventually an
# OOM kill; the subtle cap sits just above -> degradation without death.
#
# Pre-registered expectations (see faults/README.md): LOGS win the terminal
# event (OOM kill message, JVM heap errors); KERNEL sees mounting reclaim/
# page-fault activity well before app-level signals move (early-warning
# case); metrics (cadvisor container_memory_*) show the ceiling directly.
#
# Usage:
#   TARGET_SVC=carts ./svc_mem_cap.sh inject [subtle|aggressive]
#   TARGET_SVC=carts ./svc_mem_cap.sh cleanup
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="svc_mem_cap_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-logs}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="restore original memory limit via docker update"

CONTAINER="$(resolve_container "$TARGET_SVC")"
ORIG_FILE="$FAULT_STATE_DIR/${FAULT_NAME}.orig_memory"

case "${1:-}" in
  inject)
    INTENSITY="${2:-subtle}"
    case "$INTENSITY" in
      subtle)     MEM="${MEM:-300m}" ;;
      aggressive) MEM="${MEM:-160m}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    mkdir -p "$FAULT_STATE_DIR"
    docker inspect -f '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' "$CONTAINER" > "$ORIG_FILE"
    docker update -m "$MEM" --memory-swap "$MEM" "$CONTAINER" > /dev/null
    gt_begin "$INTENSITY" "{\"memory\": \"$MEM\", \"container\": \"$CONTAINER\", \"orig\": \"$(cat "$ORIG_FILE")\"}"
    ;;
  cleanup)
    read -r ORIG_MEM ORIG_SWAP < "$ORIG_FILE" 2>/dev/null || { ORIG_MEM=0; ORIG_SWAP=0; }
    if [[ "$ORIG_MEM" -gt 0 ]]; then
      docker update -m "$ORIG_MEM" --memory-swap "$ORIG_SWAP" "$CONTAINER" > /dev/null
    else
      # docker update cannot clear a memory limit ("0 = no change" in the
      # API, verified against /sys/fs/cgroup/memory.max). Restore to host
      # MemTotal instead - operationally unlimited; the approximation is
      # visible in the ground-truth record via orig="0 0".
      HOST_MEM=$(docker info -f '{{.MemTotal}}')
      docker update -m "$HOST_MEM" --memory-swap "$HOST_MEM" "$CONTAINER" > /dev/null
    fi
    gt_end
    ;;
  status)
    docker inspect -f '{{.Name}} Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}} OOMKilled={{.State.OOMKilled}}' "$CONTAINER"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
