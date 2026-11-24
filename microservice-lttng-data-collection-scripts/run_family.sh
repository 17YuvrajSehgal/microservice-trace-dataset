#!/bin/bash
# v3 collection driver: ONE fault family, one run at a time.
#
#   ./run_family.sh <recipe> [intensity] [repeats] [workload]
#       e.g.  ./run_family.sh code_lock_contended aggressive 5 steady
#
# The v2 driver (run_campaign.sh) loops over the whole matrix. v3 collects one family, checks
# it, and only then moves on, so this driver takes the family on the command line. Per run it
# does exactly what run_campaign.sh does: run_scenario.sh, then campaign_finish_run.sh
# (package, event loss, move to the archive dir), then one manifest line.
#
# Differences from v2, all recorded in each bundle's meta/load_setup.txt:
#   LOAD_SETTLE_S=30   the load runs 30 s before tracing opens, so the baseline is at steady
#                      load (v2 baselines contain the ramp-up, CAMPAIGN-ISSUES 20)
#   ARCHIVE_DIR        ~/archive/runs on the boot disk (no separate archive disk in v3)
#   EXTRA_LOAD_CMD     passed through if the family sets it below
#
# Resumable: a run whose bundle already has meta/runinfo_end.txt is skipped.
# Long unattended run:  nohup ./run_family.sh code_lock_contended aggressive 5 > ~/family.out 2>&1 &
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RECIPE="${1:?usage: run_family.sh <recipe> [intensity] [repeats] [workload]}"
INTENSITY="${2:-aggressive}"
REPEATS="${3:-5}"
WORKLOAD="${4:-steady}"
export BASELINE_S="${BASELINE_S:-60}" INJECTION_S="${INJECTION_S:-120}" RECOVERY_S="${RECOVERY_S:-60}"
export LOAD_SETTLE_S="${LOAD_SETTLE_S:-30}"
export ARCHIVE_DIR="${ARCHIVE_DIR:-$HOME/archive/runs}"
USERS_STEADY="${USERS_STEADY:-150}"
USERS_BURST="${USERS_BURST:-300}"
MANIFEST="$HOME/campaign_manifest.csv"
mkdir -p "$ARCHIVE_DIR"
[[ ! -f "$MANIFEST" ]] && echo "run_id,recipe,intensity,workload,repeat,verification,event_loss,timestamp_utc" > "$MANIFEST"

# Per-family extra load. Kept here, next to the family name, so a run cannot be started
# without it by mistake.
case "$RECIPE" in
    code_lock_contended)
        # 20 clients directly on the catalogue list endpoint for the whole run. Calibrated
        # 24-11-2026 under the normal 150-user load: median 3.9 ms with the defect off,
        # 14.6 ms with it on (5 clients: 1.5 -> 3.4 ms; 60 clients: 3.2 -> 43.3 ms).
        # The address is resolved when the load starts, AFTER `arm` recreated the container.
        LOCK_CONC="${LOCK_CONC:-20}"
        export EXTRA_LOAD_CMD="python3 $SD/faults/code-defects/loadprobe.py http://\$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \$(docker ps --format '{{.Names}}' | grep -m1 'catalogue_1'))/catalogue 1000000000 $LOCK_CONC"
        ;;
esac

if [[ "$WORKLOAD" == "burst" ]]; then USERS="$USERS_BURST"; else USERS="$USERS_STEADY"; fi
echo "=== v3 family $RECIPE: $REPEATS runs, $INTENSITY/$WORKLOAD, users=$USERS, settle=${LOAD_SETTLE_S}s ==="
[[ -n "${EXTRA_LOAD_CMD:-}" ]] && echo "    extra load: $EXTRA_LOAD_CMD"

for r in $(seq 1 "$REPEATS"); do
    RUN="${RECIPE}_${INTENSITY}_${WORKLOAD}_r${r}"
    RUN_DIR="$HOME/traces/${RECIPE}/${RUN}"
    ARCHIVED="$ARCHIVE_DIR/${RECIPE}/${RUN}"
    if [[ -f "$RUN_DIR/meta/runinfo_end.txt" || -f "$ARCHIVED/meta/runinfo_end.txt" ]]; then
        echo "[$r/$REPEATS] SKIP $RUN (already collected)"
        continue
    fi
    echo "[$r/$REPEATS] RUN  $RUN  $(date -u +%H:%M:%S)"
    PROFILE="$WORKLOAD" "$SD/run_scenario.sh" "$RECIPE" "$INTENSITY" "$RUN" "$USERS" \
        > "$HOME/${RUN}.log" 2>&1 || echo "[$r] WARN: run_scenario returned nonzero for $RUN"
    loss=$(bash "$SD/campaign_finish_run.sh" "$RUN_DIR" "$RUN" | tail -1)
    verdict="n/a"
    for d in "$RUN_DIR" "$ARCHIVED"; do
        if [[ -f "$d/verification.json" ]]; then
            verdict=$(python3 -c \
                "import json;print(json.load(open('$d/verification.json')).get('verification_status','n/a'))" 2>/dev/null || echo n/a)
            break
        fi
    done
    echo "${RUN},${RECIPE},${INTENSITY},${WORKLOAD},${r},${verdict},${loss},$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFEST"
    echo "[$r/$REPEATS] DONE $RUN -> verification=$verdict event_loss=$loss"
done
echo "=== family $RECIPE done; bundles in $ARCHIVE_DIR/$RECIPE ==="
