#!/bin/bash
# Fault recipe: an unexpected program starts inside a service container (security family).
#
# A shell is started inside the front-end container and runs a few reconnaissance commands
# (who am I, which system, which files, which processes), then exits. It happens ONCE, at
# injection, and again every REPEAT_S seconds (aggressive) or only once (subtle).
#
# A BENIGN SIMULATION on our own isolated VM: the commands only read; nothing leaves the host.
#
# WHY THIS FAMILY. A compromised service runs programs it never runs. The shape is not a rate
# or a resource: it is one `exec` of a binary never seen in that container before.
#
# HOW IT IS INJECTED, AND ITS LIMIT. Through `docker exec`, so the shell's parent is the
# container runtime (runc), not the Node process. A real attack would start it from the
# service's own process. A blueprint must therefore go by "a new program in this container",
# not by its parent.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS G3): the KERNEL shows exec of /bin/sh,
# id, uname, ls, cat and ps in the front-end's namespaces, programs never seen there in the
# baseline; METRICS, LOGS and spans show nothing.
#
# Usage:
#   ./unexpected_exec.sh inject [subtle|aggressive] | cleanup | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-front-end}"
FAULT_FAMILY="G_security"
FAULT_NAME="unexpected_exec_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"none (no user-visible effect expected)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="treat the container as compromised: stop it, keep it for analysis, redeploy from a clean image"

CONTAINER="$(resolve_container "$TARGET_SVC")"
PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
LOG="$FAULT_STATE_DIR/${FAULT_NAME}.log"
RECON='id; uname -a; ls -la / /usr/src/app; cat /etc/passwd /etc/os-release; ps -ef; env | wc -l'
running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) REPEAT_S="${REPEAT_S:-20}" ;;
      subtle)     REPEAT_S="${REPEAT_S:-0}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    docker exec "$CONTAINER" sh -c 'true' || { echo "[$FAULT_NAME] $CONTAINER has no /bin/sh"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"container\": \"$CONTAINER\", \"commands\": \"$RECON\", \"repeat_s\": $REPEAT_S, \"via\": \"docker exec\"}"
    ( n=0
      while :; do
        n=$((n + 1)); echo "$(date -u +%H:%M:%S) round $n" >> "$LOG"
        docker exec "$CONTAINER" sh -c "$RECON" >> "$LOG" 2>&1 || true
        [[ "$REPEAT_S" -gt 0 ]] || break
        sleep "$REPEAT_S"
      done ) < /dev/null > /dev/null 2>&1 &
    echo $! > "$PIDFILE"
    sleep 2
    echo "[$FAULT_NAME] shell started in $CONTAINER (repeat every ${REPEAT_S}s; 0 = once)"
    ;;
  cleanup)
    if running; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    echo "[$FAULT_NAME] stopped after $(grep -c '^[0-9:]* round' "$LOG" 2>/dev/null || echo 0) rounds"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "rounds so far: $(grep -c '^[0-9:]* round' "$LOG" 2>/dev/null || echo 0); repeating: $(running && echo yes || echo no)"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
