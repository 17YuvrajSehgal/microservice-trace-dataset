#!/bin/bash
# Fault recipe: a constant delay on one service's packets, and nothing else (tc netem delay).
#
# Every packet the container sends waits DELAY_MS. Nothing is lost, nothing is reordered and
# there is no jitter. A longer network path (another zone, a VPN, a proxy hop) does this.
#
# WHY THIS FAMILY. svc_net and anomaly_net add delay WITH jitter and loss, so they also show
# resends. net_reorder shows duplicate ACKs. Here there is no sign of trouble in TCP at all:
# every exchange is slower by one constant and the service itself is as fast as before.
#
# Restart-free: one qdisc inside the container's network namespace. Cleanup deletes it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D8): the KERNEL shows the same packets
# and no resends, with the gap between a request arriving and its answer leaving unchanged
# inside the service and one constant added on the wire; SPANS show the caller's view of the
# service slower by about the delay while the service's own time is unchanged; METRICS show
# the service's answer time almost unchanged and its callers slower.
#
# Usage:
#   TARGET_SVC=catalogue ./net_latency.sh inject [subtle|aggressive] | cleanup | status
#   env: DELAY_MS
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="net_latency_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove the delay (tc qdisc del root inside the container's network namespace)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
IFACE="${SVC_NET_IFACE:-eth0}"
container_pid() { docker inspect -f '{{.State.Pid}}' "$CONTAINER" 2>/dev/null; }
qdisc() { sudo nsenter -t "$(container_pid)" -n tc qdisc show dev "$IFACE" 2>/dev/null | head -1 | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) DELAY_MS="${DELAY_MS:-20}" ;;
      subtle)     DELAY_MS="${DELAY_MS:-5}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    PID="$(container_pid)"
    [ -n "$PID" ] && [ "$PID" != "0" ] || { echo "cannot resolve PID for $CONTAINER"; exit 1; }
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"container\": \"$CONTAINER\", \"iface\": \"$IFACE\", \"delay_ms\": $DELAY_MS}"
    sudo nsenter -t "$PID" -n tc qdisc add dev "$IFACE" root netem delay "${DELAY_MS}ms"
    echo "[$FAULT_NAME] $(qdisc)"
    ;;
  cleanup)
    PID="$(container_pid)"
    if [ -n "$PID" ] && [ "$PID" != "0" ]; then
        echo "[$FAULT_NAME] before removal: $(sudo nsenter -t "$PID" -n tc -s qdisc show dev "$IFACE" 2>/dev/null | tr '\n' ' ' | cut -c1-220)"
        sudo nsenter -t "$PID" -n tc qdisc del dev "$IFACE" root 2>/dev/null || true
    fi
    echo "[$FAULT_NAME] now: $(qdisc)"
    gt_end
    ;;
  status)
    echo "$CONTAINER $IFACE: $(qdisc)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
