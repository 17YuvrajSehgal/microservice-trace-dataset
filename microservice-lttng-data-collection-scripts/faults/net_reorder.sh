#!/bin/bash
# Fault recipe: packets of one service leave out of order (tc netem reorder).
#
# A share of the container's outgoing packets is sent at once and the rest is held back for
# DELAY_MS, so packets overtake each other. Nothing is lost. The receiver sees segments in the
# wrong order and answers with duplicate ACKs; the sender may then resend data that was never
# lost. A path with load balancing over links of different speed does this.
#
# WHY THIS FAMILY. svc_net and anomaly_net delay and LOSE packets. Here nothing is lost: the
# signs of loss (duplicate ACKs, fast retransmits) appear without any loss.
#
# netem can only reorder when it also delays: REORDER_PCT of the packets skip the delay.
#
# Restart-free: one qdisc inside the container's network namespace. Cleanup deletes it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D9): the KERNEL shows out-of-order
# segments arriving at the service's peers, duplicate ACKs and resends with no packet dropped
# anywhere; METRICS show the service's answer time up by about the delay; what users see is
# measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=catalogue ./net_reorder.sh inject [subtle|aggressive] | cleanup | status
#   env: DELAY_MS, REORDER_PCT, CORR_PCT
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="net_reorder_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove the reordering (tc qdisc del root inside the container's network namespace)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
IFACE="${SVC_NET_IFACE:-eth0}"
container_pid() { docker inspect -f '{{.State.Pid}}' "$CONTAINER" 2>/dev/null; }
qdisc() { sudo nsenter -t "$(container_pid)" -n tc qdisc show dev "$IFACE" 2>/dev/null | head -1 | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) DELAY_MS="${DELAY_MS:-10}"; REORDER_PCT="${REORDER_PCT:-25}" ;;
      subtle)     DELAY_MS="${DELAY_MS:-3}";  REORDER_PCT="${REORDER_PCT:-10}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    CORR_PCT="${CORR_PCT:-50}"
    PID="$(container_pid)"
    [ -n "$PID" ] && [ "$PID" != "0" ] || { echo "cannot resolve PID for $CONTAINER"; exit 1; }
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"container\": \"$CONTAINER\", \"iface\": \"$IFACE\", \"delay_ms\": $DELAY_MS, \"reorder_pct\": $REORDER_PCT, \"correlation_pct\": $CORR_PCT}"
    sudo nsenter -t "$PID" -n tc qdisc add dev "$IFACE" root netem delay "${DELAY_MS}ms" reorder "${REORDER_PCT}%" "${CORR_PCT}%"
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
