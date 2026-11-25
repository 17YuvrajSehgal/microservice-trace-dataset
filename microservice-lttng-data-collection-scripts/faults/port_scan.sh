#!/bin/bash
# Fault recipe: a port scan from inside one service (security family).
#
# One service's network address tries every port from 1 to 1024 on every other container of the
# stack, about 200 connections per second. Almost all are refused. Nothing is slow and nothing
# fails for users: this is what a compromised service looking for its next target does.
#
# A BENIGN SIMULATION on our own isolated VM against our own containers only; it sends no data.
#
# WHY THIS FAMILY. The dataset's other security families use CPU (resource_abuse) or bytes
# (data_exfiltration). A scan uses neither: its only mark is one source, many destinations and
# ports, and refused connections.
#
# HOW IT IS INJECTED. Not as a new container: the scanner is one process on the host that is put
# into the network namespace of an existing service (nsenter), so its packets carry that
# service's address and no new container or address appears. Its process name and pid
# namespace are the host's - a blueprint must go by the source address, not by the container
# of the process. Restart-free; cleanup stops the process.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS G1): the KERNEL shows connect calls
# returning -111 (ECONNREFUSED) at a steady high rate from one source to many ports and
# addresses, and the matching resets; METRICS, LOGS and spans show nothing (to be measured).
#
# Usage:
#   TARGET_SVC=front-end ./port_scan.sh inject [subtle|aggressive] | cleanup | status
#   env: SCAN_RATE (connections/s), FIRST_PORT, LAST_PORT
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-front-end}"
FAULT_FAMILY="G_security"
FAULT_NAME="port_scan_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"none (no user-visible effect expected)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="stop the scanning process and treat the source service as compromised"

CONTAINER="$(resolve_container "$TARGET_SVC")"
PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
LOG="$FAULT_STATE_DIR/${FAULT_NAME}.scan.log"
running() { [[ -f "$PIDFILE" ]] && sudo kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
ip_of() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) SCAN_RATE="${SCAN_RATE:-200}" ;;
      subtle)     SCAN_RATE="${SCAN_RATE:-10}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    FIRST_PORT="${FIRST_PORT:-1}"; LAST_PORT="${LAST_PORT:-1024}"
    SRC_IP="$(ip_of "$CONTAINER")"
    PEERS=""
    for c in $(stack_containers); do
        [[ "$c" == "$CONTAINER" ]] && continue
        a="$(ip_of "$c")"
        if [[ -n "$a" ]]; then PEERS="${PEERS:+$PEERS,}$a"; fi
    done
    [[ -n "$PEERS" && -n "$SRC_IP" ]] || { echo "[$FAULT_NAME] no peers or no source address"; exit 1; }
    PID="$(docker inspect -f '{{.State.Pid}}' "$CONTAINER")"
    mkdir -p "$FAULT_STATE_DIR"
    N=$(echo "$PEERS" | tr ',' '\n' | wc -l)
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"source_ip\": \"$SRC_IP\", \"peers\": $N, \"first_port\": $FIRST_PORT, \"last_port\": $LAST_PORT, \"connects_per_second\": $SCAN_RATE, \"container\": \"$CONTAINER\"}"
    sudo nsenter -t "$PID" -n python3 "$_SD/workloads/port_scan.py" "$PEERS" "$FIRST_PORT" "$LAST_PORT" "$SCAN_RATE" > "$LOG" 2>&1 < /dev/null &
    sleep 2
    SP="$(pgrep -f "^python3 .*workloads/port_scan.py" | head -1)"
    [[ -n "$SP" ]] || { echo "[$FAULT_NAME] the scanner did not start: $(tail -2 "$LOG")"; exit 1; }
    echo "$SP" > "$PIDFILE"
    echo "[$FAULT_NAME] scanning $N peers from $SRC_IP, ports $FIRST_PORT-$LAST_PORT, $SCAN_RATE connections/s"
    ;;
  cleanup)
    if running; then sudo kill "$(cat "$PIDFILE")"; sleep 2; fi
    if running; then sudo kill -9 "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    sudo pkill -f "^python3 .*workloads/port_scan.py" 2>/dev/null || true
    echo "[$FAULT_NAME] scanner stopped: $(tail -1 "$LOG" 2>/dev/null | cut -c1-200)"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "scanner running: $(running && echo yes || echo no); last line: $(tail -1 "$LOG" 2>/dev/null | cut -c1-160)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
