#!/bin/bash
# Fault recipe: slow readers (clients that take a large answer very slowly).
#
# CONNS connections each ask the service for a large answer and then read it a few hundred
# bytes per second through a very small receive buffer. The client's receive window fills, it
# advertises a window of ZERO, and the service cannot send the rest: the data waits in the
# service's send buffer and the connection stays open for minutes.
#
# WHY THIS FAMILY. slow_client (v3) is slow on the SENDING side: the service waits to read a
# request. This is the other direction: the service has the answer and cannot get rid of it.
# nagle_delayed_ack also stalls a sender, for a fixed 40 ms; here the stall has no fixed length
# and the zero window says who causes it.
#
# Restart-free: the clients are one process on the host. Cleanup stops it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D3): the KERNEL shows zero-window
# advertisements from one peer, the service's sends to that peer stalled with unsent data, and
# window probes; the service keeps answering everyone else, so METRICS may show nothing; what
# users see is measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=catalogue ./slow_reader.sh inject [subtle|aggressive] | cleanup | status
#   env: CONNS (connections), INTERVAL_S (seconds between reads), CHUNK (bytes per read), SLOW_PATH
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="slow_reader_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="close the slow connections (stop the client, or set a write timeout on the service)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
# Calibrated 27-11-2026: the list answer is 2,795 bytes, too small to fill a window; an image is 42,201.
SLOW_PATH="${SLOW_PATH:-/catalogue/images/holy_1.jpeg}"
PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
LOG="$FAULT_STATE_DIR/${FAULT_NAME}.client.log"
running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) CONNS="${CONNS:-200}" ;;
      subtle)     CONNS="${CONNS:-20}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    INTERVAL_S="${INTERVAL_S:-1.0}"; CHUNK="${CHUNK:-256}"
    IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER")"
    [[ -n "$IP" ]] || { echo "[$FAULT_NAME] no address for $CONTAINER"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"connections\": $CONNS, \"interval_s\": $INTERVAL_S, \"chunk_bytes\": $CHUNK, \"path\": \"$SLOW_PATH\", \"target_ip\": \"$IP\", \"container\": \"$CONTAINER\"}"
    nohup python3 "$_SD/workloads/slow_reader.py" "$IP" 80 "$SLOW_PATH" "$CONNS" "$INTERVAL_S" "$CHUNK" > "$LOG" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    sleep 2
    running || { echo "[$FAULT_NAME] the slow readers did not start: $(tail -2 "$LOG")"; exit 1; }
    echo "[$FAULT_NAME] slow readers started: $CONNS connections to $IP:80$SLOW_PATH, $CHUNK bytes every ${INTERVAL_S}s"
    ;;
  cleanup)
    if running; then kill "$(cat "$PIDFILE")"; sleep 2; fi
    running && kill -9 "$(cat "$PIDFILE")" 2>/dev/null || true
    echo "[$FAULT_NAME] slow readers stopped: $(tail -1 "$LOG" 2>/dev/null)"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "slow readers running: $(running && echo yes || echo no); last line: $(tail -1 "$LOG" 2>/dev/null)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
