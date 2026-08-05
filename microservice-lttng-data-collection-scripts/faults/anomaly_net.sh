#!/bin/bash
# Fault recipe: host-wide NETWORK impairment (F4) - tc netem (delay/jitter/loss)
# applied INSIDE every stack container's network namespace. Named anomaly_net to
# match anomaly_cpu + the verification_targets.json entry.
#
# WHY per-netns (not tc on the host bridge): a qdisc on the bridge *device* does
# NOT affect L2-forwarded container<->container frames (validated in wave-2: bridge
# netem left catalogue p95 flat). netem inside each container's netns (on eth0)
# impairs that container's egress - doing it to ALL stack containers gives the
# honest host-wide impairment. (svc_net.sh does this for a single service.)
#
# Pre-registered expectation (fault_catalog.md F4): metrics detect (inter-service
# latency up); TRACES localize (inter-hop gap inflates uniformly across edges);
# kernel confirms via socket backlog / retx.
#
# Usage: ./anomaly_net.sh inject [subtle|aggressive] | cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="anomaly_net"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"all services\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-traces}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-n/a}"
REMEDIATION="tc qdisc del root in every stack container netns"

IFACE="${SVC_NET_IFACE:-eth0}"
stack_containers() { docker ps --format '{{.Names}}' | grep -E '^docker-compose_.*_1$'; }

apply_each() {  # <verb: add|del>  <delay> <jitter> <loss>
    local verb="$1" n=0
    for c in $(stack_containers); do
        local pid; pid=$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || echo 0)
        [ -n "$pid" ] && [ "$pid" != 0 ] || continue
        if [ "$verb" = add ]; then
            sudo nsenter -t "$pid" -n tc qdisc add dev "$IFACE" root netem \
                delay "${2}ms" "${3}ms" distribution normal loss "${4}%" 2>/dev/null && n=$((n+1)) || true
        else
            sudo nsenter -t "$pid" -n tc qdisc del dev "$IFACE" root 2>/dev/null || true
        fi
    done
    echo "$n"
}

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     DELAY="${DELAY:-25}" JITTER="${JITTER:-8}"  LOSS="${LOSS:-0.5}" ;;
      aggressive) DELAY="${DELAY:-80}" JITTER="${JITTER:-20}" LOSS="${LOSS:-2}"   ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    N=$(apply_each add "$DELAY" "$JITTER" "$LOSS")
    echo "[anomaly_net] netem on $N container netns ($IFACE)"
    gt_begin "$INTENSITY" "{\"scope\": \"per-container netns\", \"containers\": $N, \"iface\": \"$IFACE\", \"delay_ms\": $DELAY, \"jitter_ms\": $JITTER, \"loss_pct\": $LOSS}"
    ;;
  cleanup)
    apply_each del >/dev/null
    gt_end
    ;;
  status)
    for c in $(stack_containers); do
        pid=$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || echo 0)
        [ "$pid" != 0 ] && echo "$c: $(sudo nsenter -t "$pid" -n tc qdisc show dev "$IFACE" 2>/dev/null | head -1)"
    done
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
