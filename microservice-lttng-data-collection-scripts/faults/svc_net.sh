#!/bin/bash
# Fault recipe: per-CONTAINER network impairment (F12) - tc netem inside ONE
# service's network namespace (nsenter into the container's netns, tc on eth0).
# Unlike anomaly_net (host bridge, all services), this degrades a single
# service's traffic, so RCA must localize to that service.
#
# Pre-registered expectation (fault_catalog.md F12): TRACES win localization
# (the single impaired edge inflates - client-send -> server-recv gap on one
# service only); kernel confirms via socket-level waits on that path.
#
# Usage: ./svc_net.sh inject [subtle|aggressive] | cleanup | status
#   TARGET_SVC=<svc> (default carts) - the service whose netns is impaired.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="svc_net_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-traces}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="tc qdisc del root inside the container netns"

CONTAINER="$(resolve_container "$TARGET_SVC")"
IFACE="${SVC_NET_IFACE:-eth0}"   # the container's primary interface in its netns

container_pid() { docker inspect -f '{{.State.Pid}}' "$CONTAINER" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     DELAY="${DELAY:-40}"  JITTER="${JITTER:-15}" LOSS="${LOSS:-0.5}" ;;
      aggressive) DELAY="${DELAY:-150}" JITTER="${JITTER:-40}" LOSS="${LOSS:-4}"   ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    PID="$(container_pid)"
    [ -n "$PID" ] && [ "$PID" != "0" ] || { echo "cannot resolve PID for $CONTAINER"; exit 1; }
    echo "[svc_net] netem on $CONTAINER (pid $PID) $IFACE"
    sudo nsenter -t "$PID" -n tc qdisc add dev "$IFACE" root netem \
        delay "${DELAY}ms" "${JITTER}ms" distribution normal loss "${LOSS}%"
    gt_begin "$INTENSITY" "{\"container\": \"$CONTAINER\", \"iface\": \"$IFACE\", \"delay_ms\": $DELAY, \"jitter_ms\": $JITTER, \"loss_pct\": $LOSS}"
    ;;
  cleanup)
    PID="$(container_pid)"
    if [ -n "$PID" ] && [ "$PID" != "0" ]; then
        sudo nsenter -t "$PID" -n tc qdisc del dev "$IFACE" root 2>/dev/null || true
    fi
    gt_end
    ;;
  status)
    PID="$(container_pid)"
    [ -n "$PID" ] && sudo nsenter -t "$PID" -n tc qdisc show dev "$IFACE" 2>/dev/null || echo "container not running"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status  (TARGET_SVC=$TARGET_SVC)"; exit 1 ;;
esac
