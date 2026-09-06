#!/bin/bash
# Re-run verification against already-collected bundles, with the CURRENT targets.
#
# WHY THIS IS NOT A REPAIR OF THE DATA
# -----------------------------------
# Every run this touches contains a real fault, a correct ground truth and a clean trace. What
# was wrong is the VERDICT - a threshold written from the mechanism rather than measured, or one
# carried between two machines with different baselines. Fixing a verdict costs a query; fixing
# data costs a VM run. Keeping those two apart is the whole point of CAMPAIGN-ISSUES.md.
#
# DO THIS WHILE PROMETHEUS STILL HAS THE DATA. Retention is the default 15 days and the campaign
# is about a day long, so re-scoring works today with no extra machinery. Once the VMs are gone,
# or after retention expires, the same job needs an adapter that reads each bundle's own metrics
# export instead - that export exists (440 metric files per run) but nothing reads it yet.
#
#   ./rescore_runs.sh [--dry-run] [--only <recipe>] [run_dir ...]
#
# With no run_dirs it re-scores every completed run that is not currently `confirmed` - which is
# exactly the set campaign_issues.py reports as RE-SCORE.
set -uo pipefail
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROM="${PROMETHEUS:-http://localhost:9090}"
ARCHIVE="${ARCHIVE_DIR:-/mnt/archive/runs}"
TARGETS="${VERIFY_TARGETS:-}"

DRY=0; ONLY=""
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --only) ONLY="$2"; shift ;;
        *) ARGS+=("$1") ;;
    esac
    shift
done

# Which bundles to touch. Default: everything not already confirmed.
if [[ ${#ARGS[@]} -gt 0 ]]; then
    RUNS=("${ARGS[@]}")
else
    mapfile -t RUNS < <(
        for root in "$HOME/traces" "$ARCHIVE"; do
            [[ -d "$root" ]] || continue
            find "$root" -mindepth 2 -maxdepth 2 -type d 2>/dev/null
        done | sort -u | while read -r d; do
            [[ -f "$d/meta/runinfo_end.txt" ]] || continue
            [[ -f "$d/ground_truth.json" ]] || continue      # normal runs have nothing to verify
            st=$(python3 -c "
import json,sys
try: print(json.load(open('$d/verification.json')).get('verification_status','none'))
except Exception: print('none')" 2>/dev/null)
            [[ "$st" == "confirmed" ]] && continue
            echo "$d"
        done
    )
fi

echo "=============================================================="
echo " RE-SCORE: ${#RUNS[@]} bundles, targets=${TARGETS:-<default>}"
echo " (verdicts only - no bundle's data is modified)"
echo "=============================================================="

changed=0; same=0; failed=0
for d in "${RUNS[@]}"; do
    run_id="$(basename "$d")"
    recipe="$(basename "$(dirname "$d")")"
    [[ -n "$ONLY" && "$recipe" != "$ONLY" ]] && continue
    [[ -f "$d/ground_truth.json" ]] || { echo "  SKIP $run_id (no ground truth)"; continue; }

    before=$(python3 -c "
import json
try: print(json.load(open('$d/verification.json')).get('verification_status','none'))
except Exception: print('none')" 2>/dev/null)

    if [[ "$DRY" -eq 1 ]]; then
        echo "  would re-score $run_id (currently $before)"
        continue
    fi

    # Keep the original verdict once, so a re-score can always be compared with what the
    # campaign actually recorded at collection time.
    [[ -f "$d/verification.json" && ! -f "$d/verification.as-collected.json" ]] && \
        cp "$d/verification.json" "$d/verification.as-collected.json"

    python3 "$SD/verify_injection.py" --ground-truth "$d/ground_truth.json" \
        ${TARGETS:+--targets "$TARGETS"} \
        --prometheus "$PROM" --out "$d/verification.json" \
        --plot "$d/verification.png" >/dev/null 2>&1
    rc=$?

    after=$(python3 -c "
import json
try: print(json.load(open('$d/verification.json')).get('verification_status','none'))
except Exception: print('none')" 2>/dev/null)

    if [[ "$rc" -gt 4 ]]; then
        echo "  FAIL  $run_id (verify_injection exit $rc)"; failed=$((failed+1))
    elif [[ "$before" != "$after" ]]; then
        printf "  %-52s %s -> %s\n" "$run_id" "$before" "$after"; changed=$((changed+1))
    else
        same=$((same+1))
    fi
done

echo
echo "=============================================================="
printf " %d changed, %d unchanged, %d failed\n" "$changed" "$same" "$failed"
echo " originals preserved as verification.as-collected.json"
echo "=============================================================="
