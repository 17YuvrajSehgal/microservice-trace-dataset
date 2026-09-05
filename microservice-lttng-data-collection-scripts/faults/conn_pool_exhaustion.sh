#!/bin/bash
# Fault recipe: connection-pool exhaustion on the shared datastore.
#
# A helper container opens and HOLDS connections to the database until the server refuses new
# ones. The application then queues or fails at connect time - not because the database is
# slow, but because there is no room left to talk to it.
#
# WHY THIS FAMILY EARNS ITS PLACE TWICE OVER.
#
# 1. It is the closest look-alike of `queue_backlog`: both are saturation of a shared resource
#    that everything depends on, and both leave the resource itself looking healthy - the
#    database is answering its existing connections perfectly well.
#
# 2. It is the Train Ticket analogue of queue_backlog. FAULTS-TT.md records that TT has NO
#    message broker (its booking path is synchronous REST), which is why v1 has zero
#    queue_backlog runs on that application and why the two apps could never be matched. This
#    recipe was the remodel that document proposed, and it was never written. With it, both
#    applications get a saturation fault.
#
# MECHANISM. Hold N connections open from a helper container. For MySQL the server enforces
# max_connections (151 by default), so exhaustion is the server refusing; for Mongo it is the
# connection limit per host. Either way the failure is at connect, which is what makes it
# distinct from a slow query.
#
# SAFETY. Connections are held by one container and released the instant it is removed, so
# cleanup is complete and immediate. Nothing is written to the database and no schema is
# touched - this is purely occupancy.
#
# Pre-registered expectations: KERNEL (connect stalls and failures) and LOGS (the application
# will report pool timeouts). The datastore itself shows healthy query latency, which is the
# trap.
#
# Usage:
#   ./conn_pool_exhaustion.sh inject [subtle|aggressive]
#   ./conn_pool_exhaustion.sh cleanup | status
#   env: DB_HOST  (default: the deployed app's datastore - catalogue-db on Sock Shop,
#                  the shared mysql on Train Ticket)
#        DB_PORT  (3306)
#        STRATA_APP  sockshop | trainticket
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="G_resource_leak"
FAULT_NAME="conn_pool_exhaustion"
FAULT_SCOPE="service"
# App-aware default, for the same reason as fd_exhaustion: this family has to run on BOTH
# applications or the matrices cannot match, and a recipe that needs the caller to remember
# per-app env is a recipe that will be run wrong once. Train Ticket's 20 DB services share ONE
# mysql (FAULTS-TT.md), which makes it a far bigger blast radius than Sock Shop's per-service db
# - worth noting when the two are compared.
if [[ "${STRATA_APP:-sockshop}" == "trainticket" ]]; then
    DB_HOST="${DB_HOST:-mysql}"
else
    DB_HOST="${DB_HOST:-catalogue-db}"
fi
DB_PORT="${DB_PORT:-3306}"
TARGET_SERVICE="${TARGET_SERVICE:-$DB_HOST}"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$DB_HOST\", \"every service that queries it\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="raise max_connections, or fix the client that is not returning connections"

CONTAINER="conn-pool-exhaustion"
# Sock Shop's compose project is `docker-compose`, Train Ticket's is `trainticket`, so match on
# the project network by suffix rather than by name. `bridge`/`host`/`none` do not match.
NETWORK="${NETWORK:-$(docker network ls --format '{{.Name}}' | grep -m1 -E '^(docker-compose|trainticket).*|.*_default$' || echo bridge)}"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      # MySQL default max_connections is 151. 120 leaves the application squeezed but alive;
      # 400 takes everything and makes connect fail outright.
      subtle)     CONNS="${CONNS:-120}" ;;
      aggressive) CONNS="${CONNS:-400}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    workload_start "$CONTAINER" conn_pool_exhaustion.py 1.0 \
        --network "$NETWORK" -- "$DB_HOST" "$DB_PORT" "$CONNS"
    gt_begin "$INTENSITY" "{\"db_host\": \"$DB_HOST\", \"db_port\": $DB_PORT, \"connections_held\": $CONNS, \"container\": \"$CONTAINER\", \"network\": \"$NETWORK\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
