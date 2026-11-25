#!/bin/bash
# Fault recipe: a service killed for memory again and again (memory limit below its start-up size).
#
# The container's memory limit is set below what the service needs just to start. The kernel
# kills it, Docker starts it again (restart policy "always"), and it is killed again before it
# can serve one request. This is what a wrong memory limit in a deployment file does: the
# service never comes up, and the restart counter climbs.
#
# WHY THIS FAMILY. svc_mem_cap puts the limit near the working size: the service slows down
# under reclaim and may be killed once. Here the limit is far below the start-up size, so there
# is no slow phase at all: only start, kill, start, kill. For its callers it is an outage with
# a rhythm (the restart back-off), not a slowdown.
#
# Restart-free to inject: docker update writes memory.max of the running container. Cleanup
# raises the limit to the host's memory (docker cannot clear a memory limit, see svc_mem_cap.sh)
# and starts the container if Docker is still waiting in its back-off.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS B3): the KERNEL shows the same program
# exec'd again and again in one container, each life ending in a kill inside memory reclaim;
# LOGS show the start-up banner repeated and never finished; METRICS show the service's scrape
# down; what users see is measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=carts ./oom_restart_loop.sh inject [subtle|aggressive] | cleanup | status
#   env: MEM  the limit (default 64m aggressive, 128m subtle)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="oom_restart_loop_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="raise the memory limit above the service's start-up size (docker update -m)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
ORIG_FILE="$FAULT_STATE_DIR/${FAULT_NAME}.orig_memory"
CG="/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "$CONTAINER" 2>/dev/null).scope"
state() { docker inspect -f 'status={{.State.Status}} restarts={{.RestartCount}} oom_killed={{.State.OOMKilled}}' "$CONTAINER"; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) MEM="${MEM:-64m}" ;;
      subtle)     MEM="${MEM:-128m}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    mkdir -p "$FAULT_STATE_DIR"
    docker inspect -f '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' "$CONTAINER" > "$ORIG_FILE"
    R0="$(docker inspect -f '{{.RestartCount}}' "$CONTAINER")"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"memory\": \"$MEM\", \"container\": \"$CONTAINER\", \"orig\": \"$(cat "$ORIG_FILE")\", \"restart_count_before\": $R0, \"memory_in_use_before\": $(cat "$CG/memory.current" 2>/dev/null || echo 0)}"
    docker update -m "$MEM" --memory-swap "$MEM" "$CONTAINER" > /dev/null
    echo "[$FAULT_NAME] memory limit set to $MEM ($(state))"
    ;;
  cleanup)
    read -r ORIG_MEM ORIG_SWAP < "$ORIG_FILE" 2>/dev/null || { ORIG_MEM=0; ORIG_SWAP=0; }
    if [[ "$ORIG_MEM" -gt 0 ]]; then
      docker update -m "$ORIG_MEM" --memory-swap "$ORIG_SWAP" "$CONTAINER" > /dev/null
    else
      # docker update cannot clear a memory limit; the host's total is "no limit" in practice.
      HOST_MEM=$(docker info -f '{{.MemTotal}}')
      docker update -m "$HOST_MEM" --memory-swap "$HOST_MEM" "$CONTAINER" > /dev/null
    fi
    echo "[$FAULT_NAME] memory limit restored to $(docker inspect -f '{{.HostConfig.Memory}}' "$CONTAINER") ($(state))"
    # Docker may be waiting in its restart back-off (up to a minute). Start it now, so the
    # recovery window measures the service coming back and not Docker's timer.
    docker start "$CONTAINER" > /dev/null 2>&1 || true
    gt_end
    ;;
  status)
    echo "$CONTAINER memory=$(docker inspect -f '{{.HostConfig.Memory}}' "$CONTAINER") $(state)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
