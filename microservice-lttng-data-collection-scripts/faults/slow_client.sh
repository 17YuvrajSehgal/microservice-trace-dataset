#!/bin/bash
# Fault recipe: slow clients hold a service's worker threads (thread pool exhaustion).
#
# CONNS connections each start a POST and then send the body one byte per second. The service
# reads a request body on a worker thread, so each slow connection keeps one thread. When all
# worker threads are held, normal requests wait for a thread that never comes free.
#
# WHY THIS FAMILY. It is thread pool exhaustion (CANDIDATE-PROBLEMS E3) without a restart: the
# pool size of the Java services can only be set at start-up, which would put the fault in the
# baseline. Here the pool is the stock one and the clients arrive at injection. It is also the
# slow-client case (D3) seen from the sending side. The service is idle: almost no CPU, its
# database is fast, nothing is refused by the kernel. Requests just wait inside it.
#
# Restart-free: the clients are one process on the host. Cleanup stops it; the service gets its
# threads back when the connections close.
#
# Pre-registered expectations (v3): the KERNEL shows many connections from one peer that send
# one small segment per second, the service's threads asleep on those sockets, and requests in
# flight with no CPU use and no calls to a dependency; METRICS show the service's answer time
# up or its rate down; what users see is measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=carts ./slow_client.sh inject [subtle|aggressive] | cleanup | status
#   env: CONNS (connections), INTERVAL_S (seconds between body bytes), SLOW_PATH
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="F_concurrency"
FAULT_NAME="slow_client_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="close the slow connections (stop the client, or set a request read timeout on the service)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
SLOW_PATH="${SLOW_PATH:-/carts/strata-slow-client/items}"
PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
LOG="$FAULT_STATE_DIR/${FAULT_NAME}.client.log"
running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) CONNS="${CONNS:-400}" ;;
      subtle)     CONNS="${CONNS:-150}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    INTERVAL_S="${INTERVAL_S:-1.0}"
    IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER")"
    [[ -n "$IP" ]] || { echo "[$FAULT_NAME] no address for $CONTAINER"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"connections\": $CONNS, \"interval_s\": $INTERVAL_S, \"path\": \"$SLOW_PATH\", \"target_ip\": \"$IP\", \"container\": \"$CONTAINER\"}"
    nohup python3 "$_SD/workloads/slow_client.py" "$IP" 80 "$SLOW_PATH" "$CONNS" "$INTERVAL_S" > "$LOG" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    sleep 2
    running || { echo "[$FAULT_NAME] the slow client did not start: $(tail -2 "$LOG")"; exit 1; }
    echo "[$FAULT_NAME] slow client started: $CONNS connections to $IP:80$SLOW_PATH, one byte every ${INTERVAL_S}s"
    ;;
  cleanup)
    if running; then kill "$(cat "$PIDFILE")"; sleep 2; fi
    running && kill -9 "$(cat "$PIDFILE")" 2>/dev/null || true
    echo "[$FAULT_NAME] slow client stopped: $(tail -1 "$LOG" 2>/dev/null)"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "slow client running: $(running && echo yes || echo no); last line: $(tail -1 "$LOG" 2>/dev/null)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
