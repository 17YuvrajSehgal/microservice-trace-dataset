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

# --- Co-located workload helpers (the v2 concurrency / security / config recipes) --------
#
# Several v2 faults are not "squeeze a resource" but "run a program that behaves badly":
# lock contention, priority inversion, deadlock, a mining-style CPU burner, a fork storm.
# Each is a small Python program under faults/workloads/, run in its own container beside the
# application - the same shape as noisy_neighbor, which is already the kernel-only showcase.
#
# Why a container rather than patching a service: these are the SYNTHETIC reference version of
# each signature. The realistic version lives in the code-defect branches, which patch the
# real service. Having both is the point - the pairing is the experiment (CODE-BUGS-V2.md).
#
# Every workload container is CPU-capped so a runaway program cannot take the host, and is
# named so cleanup is unambiguous.

WORKLOAD_IMAGE="${WORKLOAD_IMAGE:-python:3.12-slim}"
WORKLOAD_DIR="${WORKLOAD_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/workloads}"

# workload_start <container-name> <script.py> <cpus> [extra docker args...] [-- prog args...]
workload_start() {
    local name="$1" script="$2" cpus="$3"; shift 3
    local dockerargs=() progargs=() seen=0
    for a in "$@"; do
        if [[ "$a" == "--" ]]; then seen=1; continue; fi
        if [[ "$seen" -eq 0 ]]; then dockerargs+=("$a"); else progargs+=("$a"); fi
    done
    [[ -f "$WORKLOAD_DIR/$script" ]] || { echo "missing workload: $WORKLOAD_DIR/$script"; exit 1; }
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" --cpus="$cpus" \
        -v "$WORKLOAD_DIR/$script:/w/$script:ro" \
        "${dockerargs[@]}" \
        "$WORKLOAD_IMAGE" python3 -u "/w/$script" "${progargs[@]}" >/dev/null
    # Fail loudly if it died on startup: a fault that never ran produces a mislabelled run,
    # which is worse than a failed one because nothing downstream can tell.
    sleep 2
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != "true" ]]; then
        echo "[$FAULT_NAME] WORKLOAD FAILED TO START - logs follow:"
        docker logs "$name" 2>&1 | tail -15
        docker rm -f "$name" >/dev/null 2>&1 || true
        exit 1
    fi
}

workload_stop() { docker rm -f "$1" >/dev/null 2>&1 || true; }

workload_status() {
    docker ps --filter "name=$1" --format '{{.Names}} {{.Status}}'
    docker logs "$1" 2>&1 | tail -5
}

# --- Compose helpers (shared by the code defects and any recipe that must swap a service) ---
#
# Some faults change how a service is RUN rather than what runs beside it - a different image,
# a different resource limit. Doing that with `docker rm -f` + `docker run` is unsafe: a failed
# create leaves the service simply gone, and the replacement carries no compose labels, so
# compose then refuses to recreate it. That happened, and the stack had to be repaired by hand.
#
# Compose already knows the network, aliases, command, healthchecks and dependencies, so the
# safe move is a one-service override applied with `up -d --no-deps`. A failure leaves the
# previous container running.

fault_repo_root() { (cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" && pwd); }

# compose_stack <compose args...>   - the 7-file deployment, plus $COMPOSE_OVERRIDE if set
compose_stack() {
    local repo sd
    repo="$(fault_repo_root)"
    sd="$repo/microservice-lttng-data-collection-scripts"
    export TRACE_SCRIPTS_DIR="$sd"
    export COMPOSE_COMPATIBILITY=true
    ( cd "$repo/microservices-demo/deploy/docker-compose" && docker compose \
        -f docker-compose.yml \
        -f docker-compose.monitoring.yml \
        -f "$sd/docker-compose.metrics.yml" \
        -f "$sd/docker-compose.otel.yml" \
        -f "$sd/docker-compose.frontend-otel.yml" \
        -f "$sd/docker-compose.catalogue-otel.yml" \
        -f "$sd/docker-compose.toxiproxy.yml" \
        ${COMPOSE_OVERRIDE:+-f "$COMPOSE_OVERRIDE"} "$@" )
}

# compose_recreate <service> - recreate one service, clearing containers compose renamed out
# of the way in a previous failed attempt (they shadow the expected name and break lookups).
compose_recreate() {
    local svc="$1"
    docker ps -a --format '{{.Names}}' | grep -E "^[0-9a-f]{12}_.*_${svc}_1$" \
        | xargs -r docker rm -f >/dev/null 2>&1 || true
    compose_stack up -d --no-deps --force-recreate "$svc" >/dev/null 2>&1
}

# compose_container <service> - the container id, asked of compose rather than assumed
compose_container() {
    local id
    id="$(compose_stack ps -q "$1" 2>/dev/null | head -1)"
    [[ -n "$id" ]] && echo "$id" || resolve_container "$1"
}
