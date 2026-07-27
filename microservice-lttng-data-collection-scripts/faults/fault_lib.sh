#!/bin/bash
# Shared helpers for fault recipes.
#
# Every recipe sources this file, sets its metadata variables (FAULT_FAMILY,
# FAULT_NAME, FAULT_SCOPE, TARGET_SERVICE, EXPECTED_BLAST_RADIUS,
# EXPECTED_WINNING_MODALITY, TARGET_TRACE_VISIBILITY, REMEDIATION), and calls
# gt_begin/gt_end around its injection so every fault leaves a machine-
# readable ground-truth record with the exact injection window.
#
# Env knobs:
#   FAULT_STATE_DIR   where ground-truth JSON lands (default ~/fault-state)
#   CONTAINER_PREFIX  compose project prefix (default docker-compose, the
#                     COMPOSE_COMPATIBILITY naming used by the deployment)
#   TARGET_CONTAINER  override full container name (local testing)
#   TOXIPROXY_API     Toxiproxy admin API (default http://localhost:8474)

FAULT_STATE_DIR="${FAULT_STATE_DIR:-$HOME/fault-state}"
CONTAINER_PREFIX="${CONTAINER_PREFIX:-docker-compose}"
TOXIPROXY_API="${TOXIPROXY_API:-http://localhost:8474}"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

resolve_container() {
    if [[ -n "${TARGET_CONTAINER:-}" ]]; then
        echo "$TARGET_CONTAINER"
    else
        echo "${CONTAINER_PREFIX}_${1}_1"
    fi
}

gt_file() { echo "$FAULT_STATE_DIR/${FAULT_NAME}.ground_truth.json"; }

# gt_begin <intensity> <parameters-json>
gt_begin() {
    local intensity="$1" params="$2"
    mkdir -p "$FAULT_STATE_DIR"
    cat > "$(gt_file)" <<EOF
{
  "fault": {
    "family": "$FAULT_FAMILY",
    "name": "$FAULT_NAME",
    "scope": "$FAULT_SCOPE",
    "intensity": "$intensity",
    "parameters": $params,
    "target_service": "$TARGET_SERVICE",
    "expected_blast_radius": $EXPECTED_BLAST_RADIUS,
    "expected_winning_modality": "$EXPECTED_WINNING_MODALITY",
    "target_trace_visibility": "$TARGET_TRACE_VISIBILITY",
    "injection_start_utc": "$(now_utc)",
    "injection_end_utc": null
  },
  "remediation": { "action": "$REMEDIATION" },
  "recipe": { "script": "$(basename "$0")" }
}
EOF
    echo "[${FAULT_NAME}] injected ($intensity) at $(now_utc); ground truth -> $(gt_file)"
}

gt_end() {
    local f
    f="$(gt_file)"
    if [[ -f "$f" ]]; then
        sed -i "s/\"injection_end_utc\": null/\"injection_end_utc\": \"$(now_utc)\"/" "$f"
        echo "[${FAULT_NAME}] cleaned up at $(now_utc); window closed in $f"
    else
        echo "[${FAULT_NAME}] cleaned up (no ground-truth file found - inject not recorded?)"
    fi
}

# --- Toxiproxy helpers (recipes slow_db, error_storm) ----------------------

# toxic_add <proxy> <toxic-json>
toxic_add() {
    curl -sf -X POST "$TOXIPROXY_API/proxies/$1/toxics" -d "$2" > /dev/null
}

# toxic_del <proxy> <toxic-name>  (tolerates absent toxic)
toxic_del() {
    curl -s -X DELETE "$TOXIPROXY_API/proxies/$1/toxics/$2" > /dev/null || true
}

toxiproxy_status() {
    curl -s "$TOXIPROXY_API/proxies" | tr ',' '\n' | grep -E '"name"|"type"' || true
}
