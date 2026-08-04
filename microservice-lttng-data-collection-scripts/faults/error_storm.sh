#!/bin/bash
# Fault recipe: error storm (catalogue -> catalogue-db path).
#
# Breaks DB connections through the always-in-path Toxiproxy:
#   aggressive - reset_peer: every DB connection is RST immediately ->
#                catalogue returns 5xx bursts on all DB-backed routes
#   subtle     - timeout: connections stall TIMEOUT_MS then die -> a mix of
#                slow requests and errors (harder detection case)
#
# Pre-registered expectations (see faults/README.md): LOGS should win -
# catalogue logs driver errors with explicit cause strings; traces localize
# the failing service but carry less mechanism detail (no DB client spans);
# metrics flag the 5xx rate cheaply.
#
# Usage:
#   ./error_storm.sh inject [subtle|aggressive]
#   ./error_storm.sh cleanup
#   ./error_storm.sh status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="C_application"
FAULT_NAME="error_storm_catalogue"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-logs}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove connection-breaking toxic from catalogue-db proxy"

PROXY="catalogue-db"
TOXIC_NAME="error_storm"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)
        TIMEOUT_MS="${TIMEOUT_MS:-2000}"
        toxic_add "$PROXY" "{\"name\":\"$TOXIC_NAME\",\"type\":\"timeout\",\"stream\":\"downstream\",\"attributes\":{\"timeout\":$TIMEOUT_MS}}"
        gt_begin "$INTENSITY" "{\"toxic\": \"timeout\", \"timeout_ms\": $TIMEOUT_MS, \"proxy\": \"$PROXY\"}"
        ;;
      aggressive)
        toxic_add "$PROXY" "{\"name\":\"$TOXIC_NAME\",\"type\":\"reset_peer\",\"stream\":\"downstream\",\"attributes\":{\"timeout\":0}}"
        gt_begin "$INTENSITY" "{\"toxic\": \"reset_peer\", \"timeout_ms\": 0, \"proxy\": \"$PROXY\"}"
        ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    ;;
  cleanup)
    toxic_del "$PROXY" "$TOXIC_NAME"
    gt_end
    ;;
  status)
    toxiproxy_status
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
