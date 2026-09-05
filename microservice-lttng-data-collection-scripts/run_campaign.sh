#!/bin/bash
# Phase-2 collection campaign driver.
#
# Runs the ~40-run matrix (msr-research.md §5) by looping run_scenario.sh over
# (recipe, intensity, workload, repeat). Resumable: a run whose bundle already
# has a meta/runinfo_end.txt is skipped. Per-run QC (verify verdict) is logged
# to a campaign manifest; a summary prints at the end.
#
#   ./run_campaign.sh [--dry-run] [--only <recipe>]
#
# env: BASELINE_S (60) INJECTION_S (120) RECOVERY_S (60)  -- INJECTION_S must be
#      >= 120 for verify_injection's rate-window settling (see verify_injection).
#      USERS_STEADY (150) USERS_BURST (300)
#
# VM-only (LTTng + fault injection). Long unattended run:
#   nohup ./run_campaign.sh > ~/campaign.out 2>&1 &
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export BASELINE_S="${BASELINE_S:-60}" INJECTION_S="${INJECTION_S:-120}" RECOVERY_S="${RECOVERY_S:-60}"
USERS_STEADY="${USERS_STEADY:-150}"
USERS_BURST="${USERS_BURST:-300}"
MANIFEST="$HOME/campaign_manifest.csv"

DRY=0; ONLY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY=1;;
        --only) ONLY="$2"; shift;;
        *) echo "unknown arg: $1"; exit 1;;
    esac
    shift
done

# --- the matrix (msr-research.md §5) -------------------------------------
# Each entry: "recipe intensity workload repeats". recipe=normal is fault-free.
# 8 core faults (aggressive/steady x3), normals (steady+burst x3), intensity
# study (3 faults subtle/steady x2), workload study (2 faults burst x3... x2).
# v2: the matrix lives in ONE file, sourced by both application drivers. v1 had two drivers
# with two different matrices - 8 of 12 families here, 11 of 12 on the other application - and
# that, not any deliberate choice, is why the stored run counts came out uneven.
source "$SD/campaign_matrix.sh"
build_matrix "sockshop"

echo "=== StrataTrace Phase-2 campaign: ${#MATRIX[@]} runs "\
"(baseline ${BASELINE_S}s / injection ${INJECTION_S}s / recovery ${RECOVERY_S}s) ==="
[[ ! -f "$MANIFEST" ]] && echo "run_id,recipe,intensity,workload,repeat,verification,event_loss,timestamp_utc" > "$MANIFEST"

idx=0
for entry in "${MATRIX[@]}"; do
    idx=$((idx + 1))
    read -r recipe intensity workload repeat <<< "$entry"
    [[ -n "$ONLY" && "$recipe" != "$ONLY" ]] && continue

    RUN="${recipe}_${intensity}_${workload}_r${repeat}"
    RUN_DIR="$HOME/traces/${recipe}/${RUN}"

    # Resumable: a finished run may already have been moved to the archive, so check both.
    if [[ -f "$RUN_DIR/meta/runinfo_end.txt" ]] ||        [[ -f "${ARCHIVE_DIR:-/mnt/archive/runs}/${recipe}/${RUN}/meta/runinfo_end.txt" ]]; then
        echo "[$idx/${#MATRIX[@]}] SKIP $RUN (already collected)"
        continue
    fi
    if [[ "$workload" == "burst" ]]; then USERS="$USERS_BURST"; else USERS="$USERS_STEADY"; fi

    echo "[$idx/${#MATRIX[@]}] RUN  $RUN  (users=$USERS)"
    if [[ "$DRY" -eq 1 ]]; then continue; fi

    PROFILE="$workload" "$SD/run_scenario.sh" "$recipe" "$intensity" "$RUN" "$USERS" \
        > "$HOME/${RUN}.log" 2>&1 || echo "[$idx] WARN: run_scenario returned nonzero for $RUN"

    # Package, record event loss, and move off the collection disk - one implementation,
    # shared with the Train Ticket driver so they cannot drift apart again.
    loss=$(bash "$SD/campaign_finish_run.sh" "$RUN_DIR" "$RUN" | tail -1)
    ARCHIVED="${ARCHIVE_DIR:-/mnt/archive/runs}/${recipe}/${RUN}"

    # Read the verdict from wherever the bundle now lives.
    #
    # This read $RUN_DIR only. Once runs started being archived, $RUN_DIR no longer exists by
    # this point, so every fault run recorded n/a in the manifest while its bundle contained a
    # perfectly good `confirmed`. The data was never affected - only the index - but the
    # campaign summary and any monitoring built on it were reporting fiction.
    verdict="n/a"
    for d in "$RUN_DIR" "$ARCHIVED"; do
        if [[ -f "$d/verification.json" ]]; then
            verdict=$(python3 -c \
                "import json;print(json.load(open('$d/verification.json')).get('verification_status','n/a'))" 2>/dev/null || echo n/a)
            break
        fi
    done
    echo "${RUN},${recipe},${intensity},${workload},${repeat},${verdict},${loss},$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFEST"
    echo "[$idx/${#MATRIX[@]}] DONE $RUN -> verification=$verdict"
done

echo
echo "=== campaign summary ($MANIFEST) ==="
if [[ "$DRY" -eq 0 ]]; then
    echo "runs by verification verdict:"
    tail -n +2 "$MANIFEST" | cut -d, -f6 | sort | uniq -c
    echo "fault runs NOT confirmed (review these recipes):"
    tail -n +2 "$MANIFEST" | awk -F, '$2!="normal" && $6!="confirmed" {print "  "$1" -> "$6}'
fi
echo "=== done ==="
