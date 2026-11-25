#!/bin/bash
# Fault recipe: a database session holds a table lock again and again (catalogue-db, MySQL).
#
# One session takes a WRITE lock on the catalogue's tables, keeps it for HOLD_S seconds, lets
# go for GAP_S seconds, and repeats. While the lock is held every query of the catalogue waits
# inside the database. When it is released they all finish together. This is what a long
# maintenance statement, a schema change or a forgotten transaction does to a live service.
#
# WHY THIS FAMILY. slow_db delays every query by the same amount on the network path, and the
# database is idle. Here the network is fine and the database is where the wait is: its threads
# sleep on a lock, the catalogue's threads sleep on the socket, and answers come back in bursts.
# lock_contention is many short waits on a lock inside one process; this is few long waits on a
# lock in ANOTHER process (the database), seen by the service only as a slow reply.
#
# Restart-free: the lock session is a `docker exec` inside the database container. Cleanup
# removes its flag file and kills the session; MySQL drops the locks of a session that ends.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS E6): TRACES show the catalogue's database
# spans long and ending together; the KERNEL shows the catalogue waiting on its database
# connections with the database not on the CPU; METRICS show the catalogue's answer time up.
# What users see (errors or only slowness) is measured in the calibration, not assumed.
#
# Usage:
#   ./db_table_lock.sh inject [subtle|aggressive] | cleanup | status
#   env: HOLD_S, GAP_S  seconds the lock is held / released per cycle
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="F_concurrency"
FAULT_NAME="db_table_lock_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="${TARGET_SVC}-db"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-trace}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="end the session that holds the table lock (KILL <id>, or UNLOCK TABLES in that session)"

DB="$(resolve_container "${TARGET_SVC}-db")"
TABLES="${TABLES:-sock WRITE, sock_tag WRITE, tag WRITE}"
FLAG=/tmp/strata_table_lock
q() { docker exec "$DB" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N socksdb -e "$1"' sh "$1" 2>/dev/null; }
locked() { q "SHOW OPEN TABLES FROM socksdb WHERE In_use > 0" | wc -l; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) HOLD_S="${HOLD_S:-2}";   GAP_S="${GAP_S:-1}" ;;
      subtle)     HOLD_S="${HOLD_S:-0.3}"; GAP_S="${GAP_S:-2.7}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"hold_s\": $HOLD_S, \"gap_s\": $GAP_S, \"tables\": \"$TABLES\", \"container\": \"$DB\"}"
    # ONE session for the whole fault: while the lock is held the waiting queries can use up
    # every connection the server allows, and a new lock session could then not connect.
    docker exec -d -e HOLD_S="$HOLD_S" -e GAP_S="$GAP_S" -e TABLES="$TABLES" "$DB" sh -c '
      touch '"$FLAG"'
      while [ -f '"$FLAG"' ]; do
        echo "LOCK TABLES $TABLES; DO SLEEP($HOLD_S); UNLOCK TABLES; DO SLEEP($GAP_S);"
        sleep "$HOLD_S"; sleep "$GAP_S"     # one statement line per cycle, not a backlog in the pipe
      done | MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -n socksdb'
    sleep 1
    echo "[$FAULT_NAME] lock session started: hold ${HOLD_S}s, gap ${GAP_S}s (tables in use now: $(locked))"
    ;;
  cleanup)
    docker exec "$DB" sh -c "rm -f $FLAG; pkill -x mysql || true"
    # A killed client can leave its server thread asleep in SLEEP() with the lock still held.
    for id in $(q "SELECT id FROM information_schema.processlist WHERE user='root' AND info LIKE 'DO SLEEP%'"); do
      q "KILL $id" || true
    done
    sleep 1
    N="$(locked)"
    [[ "$N" == "0" ]] || echo "[$FAULT_NAME] WARN: $N tables are still locked"
    echo "[$FAULT_NAME] lock session ended (tables in use now: $N)"
    gt_end
    ;;
  status)
    echo "$DB tables in use: $(locked); lock session running: $(docker exec "$DB" sh -c "[ -f $FLAG ] && echo yes || echo no")"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
