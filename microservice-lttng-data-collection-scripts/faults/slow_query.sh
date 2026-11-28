#!/bin/bash
# Fault recipe: a slow query after an index is dropped (user-db, MongoDB).
#
# The user service finds a customer by name at every login. The customers collection has an
# index on `username`, so a login reads one document. The recipe drops that index: every login
# now reads the whole collection. The query is the same and its answer is the same; it just
# takes longer and costs the database CPU.
#
# Measured 28-11-2026 before writing this (explain, no change made): with the index a login
# lookup read 1 document in 0 ms; without it 32,903 documents in 33 ms. Logins run about 2.5
# per second under the 150-user load.
#
# WHY THIS FAMILY. slow_db delays the network path to a healthy, idle database. Here the path
# is fine and the DATABASE does more work for each query of one kind.
#
# NO SUBTLE SETTING: an index is there or not. `subtle` is refused.
#
# GROWING DATA. The customers collection grows with every run (the load generator registers
# users), so the cost of the scan grows over the campaign. The number of documents is written
# to the ground truth at injection.
#
# Restart-free: dropIndex and createIndex at run time. Cleanup rebuilds the index with the name
# and options saved at injection, and checks it is back.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS E5): the KERNEL shows the user-db mongod
# busy on the CPU for each login query, with the user service waiting on its database socket
# meanwhile; METRICS show the user service's login answer time up and user-db's CPU up; SPANS
# show the user service's spans for logins longer.
#
# Usage:
#   ./slow_query.sh inject [aggressive] | cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

DB_SVC="${DB_SVC:-user-db}"
FAULT_FAMILY="E_dependency"
FAULT_NAME="slow_query"
FAULT_SCOPE="service"
TARGET_SERVICE="$DB_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$DB_SVC\", \"user\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="rebuild the index: db.customers.createIndex({username: 1})"

C="$(resolve_container "$DB_SVC")"
SPECF="$FAULT_STATE_DIR/${FAULT_NAME}.index.json"
mongo_eval() { docker exec "$C" mongo --quiet users --eval "$1"; }
spec_now() { mongo_eval 'var i = db.customers.getIndexes().filter(function (x) { return x.key.username === 1; })[0]; print(i ? JSON.stringify(i) : "")'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    [[ "$INTENSITY" == "aggressive" ]] || { echo "[$FAULT_NAME] only 'aggressive': an index is there or not"; exit 1; }
    SPEC="$(spec_now)"
    [[ -n "$SPEC" ]] || { echo "[$FAULT_NAME] no username index on users.customers - run cleanup first"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"
    echo "$SPEC" > "$SPECF"
    NAME="$(echo "$SPEC" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
    DOCS="$(mongo_eval 'print(db.customers.count())')"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"container\": \"$C\", \"collection\": \"users.customers\", \"index\": \"$NAME\", \"documents\": $DOCS}"
    mongo_eval "printjson(db.customers.dropIndex('$NAME'))" > /dev/null
    echo "[$FAULT_NAME] dropped index $NAME on users.customers ($DOCS documents); left: $(spec_now | wc -c) bytes of spec (0 = gone)"
    ;;
  cleanup)
    if [[ -n "$(spec_now)" ]]; then
      echo "[$FAULT_NAME] the index is already there"
    elif [[ -s "$SPECF" ]]; then
      SPEC="$(cat "$SPECF")"
      mongo_eval 'var s = '"$SPEC"'; var o = {name: s.name}; if (s.unique) o.unique = true; if (s.sparse) o.sparse = true; printjson(db.customers.createIndex(s.key, o))' > /dev/null
    else
      echo "[$FAULT_NAME] WARN: no saved spec; rebuilding a plain index on username"
      mongo_eval 'printjson(db.customers.createIndex({username: 1}))' > /dev/null
    fi
    [[ -n "$(spec_now)" ]] && echo "[$FAULT_NAME] index on username is back: $(spec_now | cut -c1-120)" || echo "[$FAULT_NAME] WARN: the index is NOT back"
    gt_end
    ;;
  status)
    echo "users.customers username index: $(spec_now | cut -c1-160)"
    ;;
  *)
    echo "usage: $0 inject [aggressive] | cleanup | status"; exit 1 ;;
esac
