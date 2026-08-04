#!/bin/bash
# Fault recipe: message-queue backlog (pause the queue consumer).
#
# Pauses queue-master, the sole consumer of the shipping queue on RabbitMQ.
# Orders keep succeeding (the async publish still works) while shipping
# tasks silently pile up in the queue - a "silent degradation" fault with
# NO user-visible error.
#
# Pre-registered expectations (see faults/README.md): the hardest detection
# case in the catalog. App-level signals barely move (no errors, orders
# 200). KERNEL wins detection: queue-master's cgroup falls silent while
# rabbitmq's socket/memory activity keeps growing; cadvisor's rabbitmq
# container_memory trend is the metrics-side echo. RabbitMQ itself is a
# trace blind spot (3.6, no instrumentation).
#
# Usage:
#   ./queue_backlog.sh inject
#   ./queue_backlog.sh cleanup
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-queue-master}"
FAULT_FAMILY="D_dependency"
FAULT_NAME="queue_backlog"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"queue-master\", \"rabbitmq\", \"shipping\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="docker unpause queue-master; consumer drains the backlog"

CONTAINER="$(resolve_container "$TARGET_SVC")"

case "${1:-}" in
  inject)
    docker pause "$CONTAINER" > /dev/null
    gt_begin "aggressive" "{\"mechanism\": \"docker pause of sole queue consumer\", \"container\": \"$CONTAINER\"}"
    ;;
  cleanup)
    docker unpause "$CONTAINER" > /dev/null || true
    gt_end
    ;;
  status)
    docker inspect -f '{{.Name}} Paused={{.State.Paused}}' "$CONTAINER"
    ;;
  *)
    echo "usage: $0 inject | cleanup | status"; exit 1 ;;
esac
