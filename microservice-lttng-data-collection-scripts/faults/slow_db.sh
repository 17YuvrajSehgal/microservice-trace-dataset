#!/bin/bash
# Fault recipe: slow database (catalogue -> catalogue-db path).
#
# Adds a Toxiproxy latency toxic on the always-in-path catalogue-db proxy
# (see docker-compose.toxiproxy.yml). Models the classic "slow query /
# saturated DB" postmortem pattern without touching the database itself.
#
# Pre-registered expectations (see faults/README.md): catalogue-db is a
# deliberate trace BLIND SPOT (no OTel in mysql, no DB client spans in
# catalogue) - traces see only the inflated catalogue server span, logs stay
# quiet (slow, not failing), service metrics show latency but not the cause.
# The kernel modality should win the mechanism question via wait attribution
# (catalogue blocked on the DB socket, catalogue-db doing the work).
#
# Usage:
#   ./slow_db.sh inject [subtle|aggressive]
#   ./slow_db.sh cleanup
#   ./slow_db.sh status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="C_application"
FAULT_NAME="${FAULT_NAME:-slow_db_catalogue}"
FAULT_SCOPE="service"
TARGET_SERVICE="${TARGET_SERVICE:-catalogue-db}"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue-db\", \"catalogue\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="remove latency toxic from the DB proxy"

# Proxy name in toxiproxy-config(-tt).json: "catalogue-db" (Sock Shop) or "mysql" (Train Ticket).
PROXY="${PROXY:-catalogue-db}"
TOXIC_NAME="slowdb_latency"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     LAT_MS="${LAT_MS:-60}"  JITTER_MS="${JITTER_MS:-20}" ;;
      aggressive) LAT_MS="${LAT_MS:-500}" JITTER_MS="${JITTER_MS:-100}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    toxic_add "$PROXY" "{\"name\":\"$TOXIC_NAME\",\"type\":\"latency\",\"stream\":\"downstream\",\"attributes\":{\"latency\":$LAT_MS,\"jitter\":$JITTER_MS}}"
    gt_begin "$INTENSITY" "{\"latency_ms\": $LAT_MS, \"jitter_ms\": $JITTER_MS, \"stream\": \"downstream\", \"proxy\": \"$PROXY\"}"
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
