#!/bin/bash
# Fault recipe: a bandwidth cap on one service (tc tbf on the container's interface).
#
# The container may send only RATE bits per second. Nothing is lost at first and there is no
# fixed delay: packets wait in a queue when the service sends faster than the cap, and are
# dropped only when they would wait longer than LATENCY_MS. This is what a traffic-shaping
# rule, a small network plan or a throttled link does.
#
# WHY THIS FAMILY. svc_net and anomaly_net add delay and loss to every packet, whatever the
# load. A cap does nothing while the service sends less than the cap and bites only above it,
# so small answers are fast and large or frequent ones are slow.
#
# Restart-free: one qdisc inside the container's network namespace. Cleanup deletes it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D4): the KERNEL shows the service's
# sending rate flat at the cap with packets leaving at a steady pace; METRICS show its answer
# time up; what users see is measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=catalogue ./net_bandwidth.sh inject [subtle|aggressive] | cleanup | status
#   env: RATE_KBIT, BURST_KB, LATENCY_MS
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="net_bandwidth_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove the rate limit (tc qdisc del root inside the container's network namespace)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
IFACE="${SVC_NET_IFACE:-eth0}"
container_pid() { docker inspect -f '{{.State.Pid}}' "$CONTAINER" 2>/dev/null; }
qdisc() { sudo nsenter -t "$(container_pid)" -n tc qdisc show dev "$IFACE" 2>/dev/null | head -1 | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) RATE_KBIT="${RATE_KBIT:-2000}" ;;
      subtle)     RATE_KBIT="${RATE_KBIT:-4000}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    BURST_KB="${BURST_KB:-32}"; LATENCY_MS="${LATENCY_MS:-400}"
    PID="$(container_pid)"
    [ -n "$PID" ] && [ "$PID" != "0" ] || { echo "cannot resolve PID for $CONTAINER"; exit 1; }
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"container\": \"$CONTAINER\", \"iface\": \"$IFACE\", \"rate_kbit\": $RATE_KBIT, \"burst_kb\": $BURST_KB, \"latency_ms\": $LATENCY_MS}"
    sudo nsenter -t "$PID" -n tc qdisc add dev "$IFACE" root tbf rate "${RATE_KBIT}kbit" burst "${BURST_KB}kb" latency "${LATENCY_MS}ms"
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
