#!/bin/bash
# Fault-aware run driver: collect a full four-modality bundle across a
# baseline -> injection -> recovery structure, then verify the injection and
# audit the alignment. This is the Phase-2 campaign workhorse.
#
#   run_scenario.sh <recipe> <intensity> [run_id] [users]
#     <recipe>    a script in faults/ WITHOUT extension (e.g. slow_db)
#     <intensity> subtle | aggressive  (single-intensity recipes ignore it)
#
#   env: BASELINE_S (60) INJECTION_S (120) RECOVERY_S (60)
#        TARGET_SVC (passed through to service-targeted recipes)
#        PROMETHEUS FRONTEND_HOST
#
# The whole run is traced continuously; the fault is injected BASELINE_S in
# and removed after INJECTION_S, so every bundle contains onset and recovery
# (required for the explanation/repair tasks). collect_trace.sh self-heals
# stale LTTng state, so no manual reset is needed between runs.
#
# VM-only (needs LTTng + performs fault injection). For long unattended runs
# over flaky SSH: nohup ./run_scenario.sh slow_db aggressive r01 >log 2>&1 &
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export TRACE_SCRIPTS_DIR="$SD"

RECIPE="${1:?usage: run_scenario.sh <recipe> <intensity> [run_id] [users]}"
INTENSITY="${2:-aggressive}"
RUN="${3:-${RECIPE}_$(date -u +%H%M%S 2>/dev/null || echo run)}"
USERS="${4:-200}"
BASELINE_S="${BASELINE_S:-60}"
INJECTION_S="${INJECTION_S:-120}"
RECOVERY_S="${RECOVERY_S:-60}"
DURATION=$((BASELINE_S + INJECTION_S + RECOVERY_S))
PROM="${PROMETHEUS:-http://localhost:9090}"
FRONTEND="${FRONTEND_HOST:-http://localhost:80}"

# RECIPE="normal" is a fault-free reference run (trace + load + audit, no
# injection/verify). Any other value must name an executable faults/ recipe.
NORMAL=0
if [[ "$RECIPE" == "normal" ]]; then
    NORMAL=1
else
    RECIPE_SH="$SD/faults/${RECIPE}.sh"
    [[ -x "$RECIPE_SH" ]] || { echo "no such recipe: $RECIPE_SH"; exit 1; }
fi

# Workload shape passed through to the load generator (steady|burst).
PROFILE="${PROFILE:-steady}"
# Load generator (default = the Sock Shop one alongside this script). Another app exports
# LOAD_GEN=<its load_generator.py> plus the collect_trace app-profile env (TRACE_APP,
# CONTAINER_REGEX, LOG_CONTAINER_REGEX, OTLP_SRC) and CONTAINER_PREFIX for the fault recipes.
LOAD_GEN="${LOAD_GEN:-$SD/load_generator.py}"

# Per-run fault-state dir so exactly one ground_truth.json belongs to this run.
export FAULT_STATE_DIR="$HOME/fault-state/$RUN"
rm -rf "$FAULT_STATE_DIR" "$HOME/traces/$RECIPE/$RUN" "$HOME/${RUN}_metrics"
mkdir -p "$FAULT_STATE_DIR"

if ! curl -sf -m 8 "$PROM/api/v1/query?query=up" >/dev/null 2>&1; then
    echo "WARNING: Prometheus unreachable at $PROM - metrics + verification will be empty."
fi

echo "[$RUN] scenario=$RECIPE intensity=$INTENSITY workload=$PROFILE duration=${DURATION}s "\
"(baseline ${BASELINE_S}s / injection ${INJECTION_S}s / recovery ${RECOVERY_S}s)"

# 1) continuous tracing for the whole window (scenario dir = recipe name)
( cd "$SD" && ./collect_trace.sh "$RECIPE" "$RUN" "$DURATION" ) &
TRACE_PID=$!

# 2) continuous load for the whole window
python3 "$LOAD_GEN" --host "$FRONTEND" --users "$USERS" \
    --duration "$DURATION" --profile "$PROFILE" --think-min 0.1 --think-max 0.3 \
    --output "$HOME/${RUN}_load.csv" > "$HOME/${RUN}_load.log" 2>&1 &
LOAD_PID=$!

# 3) baseline -> inject -> hold -> cleanup -> recovery (the recipe stamps the
#    exact injection window into ground_truth.json via gt_begin/gt_end).
#    Skipped entirely for a normal (fault-free) reference run.
if [[ "$NORMAL" -eq 0 ]]; then
    sleep "$BASELINE_S"
    echo "[$RUN] injecting $RECIPE ($INTENSITY) at baseline+${BASELINE_S}s"
    "$RECIPE_SH" inject "$INTENSITY" || echo "[$RUN] WARN: inject returned nonzero"
    sleep "$INJECTION_S"
    echo "[$RUN] cleaning up $RECIPE"
    "$RECIPE_SH" cleanup || echo "[$RUN] WARN: cleanup returned nonzero"
fi

# recovery window elapses while tracing continues to the end
wait "$TRACE_PID" 2>/dev/null || true
kill "$LOAD_PID" 2>/dev/null || true
wait "$LOAD_PID" 2>/dev/null || true

# 4) metrics for the exact run window (clock-anchored runinfo)
RUN_DIR="$HOME/traces/$RECIPE/$RUN"
S=$(grep timestamp_utc "$RUN_DIR/meta/runinfo_start.txt" 2>/dev/null | cut -d= -f2)
E=$(grep timestamp_utc "$RUN_DIR/meta/runinfo_end.txt" 2>/dev/null | cut -d= -f2)
PROMETHEUS="$PROM" STEP=5s "$SD/download_metrics_full.sh" "$S" "$E" "$HOME/${RUN}_metrics" || true

# 5) verify the injection actually moved its target metric(s) (fault runs only)
if [[ "$NORMAL" -eq 0 ]]; then
    GT=$(ls "$FAULT_STATE_DIR"/*.ground_truth.json 2>/dev/null | head -1)
    if [[ -n "$GT" ]]; then
        cp "$GT" "$RUN_DIR/ground_truth.json"
        python3 "$SD/verify_injection.py" --ground-truth "$GT" \
            --prometheus "$PROM" --out "$RUN_DIR/verification.json" \
            --plot "$RUN_DIR/verification.png" || true
    else
        echo "[$RUN] WARN: no ground_truth.json produced by the recipe"
    fi
fi

# 6) cross-modality alignment audit
python3 "$SD/audit_alignment.py" "$RUN_DIR" \
    --load-csv "$HOME/${RUN}_load.csv" --metrics-dir "$HOME/${RUN}_metrics" || true

echo "[$RUN] DONE. bundle=$RUN_DIR verification=$(python3 -c "import json,sys; print(json.load(open('$RUN_DIR/verification.json')).get('verification_status','n/a'))" 2>/dev/null || echo n/a)"
