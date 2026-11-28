#!/bin/bash
# Fault recipe: a SYN flood on one service (half-open connections that are never finished).
#
# hping3 sends connection attempts (SYN) to the service's port from an address that does not
# exist. The service answers each one (SYN-ACK) and waits for the third packet, which never
# comes, and sends its answer again a few times. With SYN cookies on (they are, measured
# 28-11-2026) the kernel stops keeping state once its queue is full and real clients still
# get in; the cost is kernel work for every fake attempt.
#
# WHY THIS FAMILY. port_scan tries many ports once each and is refused; slow_client finishes its
# connections and then holds them. Here one port gets a stream of attempts that are never
# finished.
#
# SAFETY. The fake source is an unused address INSIDE the service's own Docker network, so the
# service's answers stay on the host: nothing is sent to any outside address. The recipe checks
# that no container uses that address before it starts.
#
# Restart-free: one process on the host. Cleanup stops it. The service keeps re-sending its
# answers to the fake address for up to about a minute after cleanup (the kernel's retries),
# so the recovery window starts with some of them.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS G5): the KERNEL shows thousands of
# connection attempts per second to one port from one address, every one answered and none
# finished, and the answers sent again; METRICS show little or nothing for the service (SYN
# cookies), so this is a kernel-only family unless calibration shows otherwise.
#
# Usage:
#   TARGET_SVC=front-end ./syn_flood.sh inject [subtle|aggressive] | cleanup | status
#   env: RATE (attempts per second), TARGET_PORT, FAKE_IP
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-front-end}"
FAULT_FAMILY="G_security"
FAULT_NAME="syn_flood_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="block the source (firewall rule) and keep SYN cookies on"

CONTAINER="$(resolve_container "$TARGET_SVC")"
PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
LOG="$FAULT_STATE_DIR/${FAULT_NAME}.log"
running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) RATE="${RATE:-20000}" ;;
      subtle)     RATE="${RATE:-2000}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    command -v hping3 > /dev/null || { echo "[$FAULT_NAME] hping3 is not installed (sudo apt-get install -y hping3)"; exit 1; }
    IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER")"
    TARGET_PORT="${TARGET_PORT:-$(case "$TARGET_SVC" in front-end) echo 8079 ;; *) echo 80 ;; esac)}"
    FAKE_IP="${FAKE_IP:-${IP%.*}.250}"
    # The fake source must be on the service's own network and used by nobody.
    if docker network inspect $(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$CONTAINER") \
         -f '{{range .Containers}}{{.IPv4Address}} {{end}}' | tr ' ' '\n' | grep -q "^${FAKE_IP}/"; then
      echo "[$FAULT_NAME] $FAKE_IP is used by a container; set FAKE_IP to a free address"; exit 1
    fi
    mkdir -p "$FAULT_STATE_DIR"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"container\": \"$CONTAINER\", \"target_ip\": \"$IP\", \"port\": $TARGET_PORT, \"fake_source\": \"$FAKE_IP\", \"rate_per_s\": $RATE}"
    nohup sudo hping3 -q -S -p "$TARGET_PORT" -a "$FAKE_IP" -i "u$(( 1000000 / RATE ))" "$IP" > "$LOG" 2>&1 < /dev/null &
    sleep 2
    pgrep -f "hping3 -q -S -p $TARGET_PORT -a $FAKE_IP" | head -1 > "$PIDFILE"
    running || { echo "[$FAULT_NAME] hping3 did not start: $(tail -2 "$LOG")"; exit 1; }
    echo "[$FAULT_NAME] SYN flood started: $RATE per second to $IP:$TARGET_PORT from $FAKE_IP (unused, on the same network)"
    ;;
  cleanup)
    if [[ -f "$PIDFILE" ]]; then sudo kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    sudo pkill -f "hping3 -q -S -p" 2>/dev/null || true
    sleep 1
    echo "[$FAULT_NAME] SYN flood stopped (hping3 left: $(pgrep -fc 'hping3 -q -S -p' || true))"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "SYN flood running: $(running && echo yes || echo no)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
