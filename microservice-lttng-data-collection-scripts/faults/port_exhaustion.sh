#!/bin/bash
# Fault recipe: a service runs out of local (ephemeral) ports.
#
# Every outgoing TCP connection needs a local port from net.ipv4.ip_local_port_range, and a
# port that was just closed stays reserved for a minute (TIME_WAIT). A service that opens a
# new connection per call uses its ports far faster than they come back. Here the range of
# ONE container is shrunk, so the service keeps working until the ports are used up and then
# connect() fails with EADDRNOTAVAIL ("cannot assign requested address").
#
# WHY THIS FAMILY. It looks like a broken dependency - the service reports that it cannot
# reach its database - while the database and the network are healthy and nothing is refused
# or reset on the wire: the connection attempt never leaves the service. It is the look-alike
# of error_storm (which resets on the wire) and fd_exhaustion (EMFILE, a different limit).
#
# Restart-free: the range is written into the container's network namespace with nsenter,
# and written back at cleanup.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D1): the KERNEL shows connect() returning
# -99 in one process and NO packets leaving for those attempts; LOGS carry the error string;
# metrics show the 5xx rate of the service; spans show which calls fail.
#
# Usage:
#   TARGET_SVC=catalogue ./port_exhaustion.sh inject [subtle|aggressive] | cleanup | status
#   env: PORTS  number of local ports left (default 200 aggressive, 1500 subtle)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="port_exhaustion_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="restore net.ipv4.ip_local_port_range; reuse connections (a pool, keep-alive) instead of one per call"

CONTAINER="$(resolve_container "$TARGET_SVC")"
ORIG_FILE="$FAULT_STATE_DIR/${FAULT_NAME}.orig_range"
PID="$(docker inspect -f '{{.State.Pid}}' "$CONTAINER" 2>/dev/null || echo 0)"
range() { sudo nsenter -t "$PID" -n sysctl -n net.ipv4.ip_local_port_range | tr '\t' ' ' | tr -s ' '; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) PORTS="${PORTS:-200}" ;;
      subtle)     PORTS="${PORTS:-1500}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    [[ "$PID" != 0 ]] || { echo "[$FAULT_NAME] $CONTAINER is not running"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"
    BEFORE="$(range)"
    echo "$BEFORE" > "$ORIG_FILE"
    LO="${BEFORE%% *}"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"local_ports\": $PORTS, \"range_before\": \"$BEFORE\", \"range_during\": \"$LO $((LO + PORTS - 1))\", \"container\": \"$CONTAINER\"}"
    sudo nsenter -t "$PID" -n sysctl -q -w net.ipv4.ip_local_port_range="$LO $((LO + PORTS - 1))"
    echo "[$FAULT_NAME] local port range $BEFORE -> $(range)"
    ;;
  cleanup)
    ORIG="$(cat "$ORIG_FILE" 2>/dev/null || echo '32768 60999')"
    sudo nsenter -t "$PID" -n sysctl -q -w net.ipv4.ip_local_port_range="$ORIG"
    NOW="$(range)"
    [[ "$NOW" == "$ORIG" ]] || echo "[$FAULT_NAME] WARN: restore asked for '$ORIG', the kernel reports '$NOW'"
    echo "[$FAULT_NAME] local port range restored to $NOW"
    gt_end
    ;;
  status)
    echo "$CONTAINER ip_local_port_range=$(range)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
