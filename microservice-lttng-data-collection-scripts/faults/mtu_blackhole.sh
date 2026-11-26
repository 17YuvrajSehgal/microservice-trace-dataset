#!/bin/bash
# Fault recipe: an MTU black hole in front of one service.
#
# The host side of the service's network link gets a small MTU while the service itself keeps
# 1500. The service sends full-size packets; the bridge cannot pass them and drops them without
# telling anyone (no "fragmentation needed" message comes back on a bridge). Small packets pass.
# So short requests and short answers work, and any answer larger than the small MTU stalls: the
# service retransmits the large packets, they are dropped again, until the caller gives up.
#
# WHY THIS FAMILY. Every network fault collected so far hits all packets of a service (delay,
# loss, a rate limit). This one hits packets by SIZE: the same service answers some requests at
# once and never answers others.
#
# Restart-free: one `ip link set mtu` on the host. Cleanup sets it back to the service side's MTU.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D5): the KERNEL shows the service's large
# segments sent again and again with no answer, small ones normal; METRICS show the caller's
# answer time and errors up for the requests with large answers; spans show those calls ending
# in timeouts. Measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=catalogue ./mtu_blackhole.sh inject [subtle|aggressive] | cleanup | status
#   env: MTU (default 576 aggressive, 1200 subtle)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="mtu_blackhole_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="give the link the same MTU on both sides (ip link set <veth> mtu 1500)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
veth() {   # the host-side interface of the container's eth0
    local pid idx
    pid="$(docker inspect -f '{{.State.Pid}}' "$CONTAINER")"
    idx="$(sudo nsenter -t "$pid" -n ip -o link show eth0 | sed -E 's/.*eth0@if([0-9]+).*/\1/')"
    ip -o link | awk -F': ' -v i="$idx" '$1 == i {print $2}' | cut -d@ -f1
}
inner_mtu() { sudo nsenter -t "$(docker inspect -f '{{.State.Pid}}' "$CONTAINER")" -n cat /proc/sys/net/ipv4/ip_no_pmtu_disc >/dev/null 2>&1; sudo nsenter -t "$(docker inspect -f '{{.State.Pid}}' "$CONTAINER")" -n ip -o link show eth0 | sed -E 's/.* mtu ([0-9]+).*/\1/'; }
mtu_of() { ip -o link show "$1" | sed -E 's/.* mtu ([0-9]+).*/\1/'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) MTU="${MTU:-576}" ;;
      subtle)     MTU="${MTU:-1200}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    V="$(veth)"; [[ -n "$V" ]] || { echo "[$FAULT_NAME] cannot find the host side of $CONTAINER's link"; exit 1; }
    BEFORE="$(mtu_of "$V")"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"host_interface\": \"$V\", \"mtu\": $MTU, \"mtu_before\": $BEFORE, \"service_mtu\": $(inner_mtu), \"container\": \"$CONTAINER\"}"
    sudo ip link set "$V" mtu "$MTU"
    echo "[$FAULT_NAME] $V mtu $BEFORE -> $(mtu_of "$V") (service side $(inner_mtu))"
    ;;
  cleanup)
    V="$(veth)"; IN="$(inner_mtu)"
    sudo ip link set "$V" mtu "$IN"
    echo "[$FAULT_NAME] $V mtu restored to $(mtu_of "$V") (service side $IN)"
    gt_end
    ;;
  status)
    V="$(veth)"; echo "$CONTAINER: host side $V mtu $(mtu_of "$V"), service side $(inner_mtu)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
