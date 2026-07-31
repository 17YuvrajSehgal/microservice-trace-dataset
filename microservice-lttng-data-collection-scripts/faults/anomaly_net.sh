#!/bin/bash
# Fault recipe: host-wide NETWORK impairment (tc netem delay/jitter/loss + tbf
# rate cap) on the Docker bridge the stack runs on. Fills the F4 gap. Runs on
# the HOST with sudo (tc acts on the bridge iface), not in a container. Named
# anomaly_net to match anomaly_cpu + the existing verification_targets.json entry.
#
# Pre-registered expectation (fault_catalog.md F4): metrics detect (netdev
# throughput drop, inter-service latency up); TRACES localize (client-send ->
# server-recv inter-hop gap inflates uniformly across edges - distinguishes
# network from service slowness); kernel confirms via socket backlog / retx.
#
# Usage: ./anomaly_net.sh inject [subtle|aggressive] | cleanup | status
#   NET_IFACE=<iface> to override the auto-detected bridge.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="A_host_resource"
FAULT_NAME="anomaly_net"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS='["host", "all services"]'
EXPECTED_WINNING_MODALITY="traces"
TARGET_TRACE_VISIBILITY="n/a"
REMEDIATION="tc qdisc del root on the bridge iface"

# Bridge backing the compose network (br-<netid12>), else docker0.
detect_iface() {
    local net brid
    net=$(docker network ls --format '{{.Name}}' 2>/dev/null | grep -E 'docker-compose|sock' | head -1)
    if [ -n "$net" ]; then
        brid=$(docker network inspect "$net" -f '{{.Id}}' 2>/dev/null | cut -c1-12)
        if [ -n "$brid" ] && ip -o link show "br-$brid" >/dev/null 2>&1; then
            echo "br-$brid"; return
        fi
    fi
    echo docker0
}
IFACE="${NET_IFACE:-$(detect_iface)}"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     DELAY="${DELAY:-30}"  JITTER="${JITTER:-10}" LOSS="${LOSS:-0.5}" RATE="${RATE:-100mbit}" ;;
      aggressive) DELAY="${DELAY:-100}" JITTER="${JITTER:-30}" LOSS="${LOSS:-3}"   RATE="${RATE:-20mbit}"  ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    echo "[anomaly_net] applying netem on $IFACE"
    sudo tc qdisc add dev "$IFACE" root handle 1: netem \
        delay "${DELAY}ms" "${JITTER}ms" distribution normal loss "${LOSS}%"
    sudo tc qdisc add dev "$IFACE" parent 1: handle 10: tbf \
        rate "$RATE" burst 32kbit latency 400ms
    gt_begin "$INTENSITY" "{\"iface\": \"$IFACE\", \"delay_ms\": $DELAY, \"jitter_ms\": $JITTER, \"loss_pct\": $LOSS, \"rate\": \"$RATE\"}"
    ;;
  cleanup)
    sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true
    gt_end
    ;;
  status)
    sudo tc qdisc show dev "$IFACE" 2>/dev/null || true
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status  (iface=$IFACE)"; exit 1 ;;
esac
