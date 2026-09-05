#!/bin/bash
# Train Ticket Phase-2 collection campaign driver. Same methodology as the Sock Shop
# run_campaign.sh ("same as OB"): loop run_scenario_tt.sh over (recipe, intensity, workload,
# repeat), continuous tracing with a baseline -> injection -> recovery structure, per-run verify +
# alignment audit, gzip the kernel CTF, resumable (skip bundles that already have runinfo_end.txt).
#
# The ONE addition over run_campaign.sh: TT fault targets + blast radii differ per fault, so each
# service-targeted recipe carries TARGET_SVC + EXPECTED_BLAST_RADIUS + winning-modality + trace-
# visibility from FAULTS-TT.md (host-scoped anomalies use the recipe defaults).
#
#   ./run_campaign_tt.sh [--dry-run] [--only <recipe>]
#   env: BASELINE_S (60) INJECTION_S (120) RECOVERY_S (60) USERS_STEADY (20) USERS_BURST (40)
#
# VM-only. Long unattended run:  nohup ./run_campaign_tt.sh > ~/tt_campaign.out 2>&1 &
set -uo pipefail
TTD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export BASELINE_S="${BASELINE_S:-60}" INJECTION_S="${INJECTION_S:-120}" RECOVERY_S="${RECOVERY_S:-60}"
USERS_STEADY="${USERS_STEADY:-20}"
USERS_BURST="${USERS_BURST:-40}"
MANIFEST="$HOME/tt_campaign_manifest.csv"

DRY=0; ONLY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY=1;;
        --only) ONLY="$2"; shift;;
        *) echo "unknown arg: $1"; exit 1;;
    esac
    shift
done

# --- per-fault TT config (FAULTS-TT.md); host-scoped anomalies omitted -> recipe defaults ------
declare -A TARGET BLAST MODALITY TRACEVIS PXY TSVC FNAME EXTRAENV
# CALIBRATED 2026-08-04 on the VM: TT's baseline RAM (~33GB) is far higher than Sock Shop's, so the
# recipe's default anomaly_mem FRAC (88% aggressive) drives MemAvailable to ~5% or OOM-kills the
# stressor (erratic). FRAC=35 holds ~22GB -> MemAvailable ~13% (<0.25 gate, fires) with ~8GB
# headroom so the JVMs/lttng survive a 120s injection. Only anomaly_mem reads FRAC.
EXTRAENV[anomaly_mem]="FRAC=35"
# service-targeted (docker update / netem / docker pause): use TARGET_SVC
TARGET[svc_cpu_cap]=ts-travel-service
BLAST[svc_cpu_cap]='["ts-travel-service","ts-preserve-service","ts-gateway-service","ts-ui-dashboard"]'
MODALITY[svc_cpu_cap]=kernel; TRACEVIS[svc_cpu_cap]=covered
TARGET[svc_mem_cap]=ts-order-service
BLAST[svc_mem_cap]='["ts-order-service","ts-preserve-service","ts-inside-payment-service","ts-gateway-service"]'
MODALITY[svc_mem_cap]=logs; TRACEVIS[svc_mem_cap]=covered
TARGET[svc_net]=ts-basic-service
BLAST[svc_net]='["ts-basic-service","ts-travel-service","ts-gateway-service","ts-ui-dashboard"]'
MODALITY[svc_net]=traces; TRACEVIS[svc_net]=covered
TARGET[dependency_outage]=ts-seat-service
BLAST[dependency_outage]='["ts-seat-service","ts-travel-service","ts-preserve-service","ts-order-service"]'
MODALITY[dependency_outage]=traces; TRACEVIS[dependency_outage]=covered
# toxiproxy on the SHARED mysql (needs docker-compose.toxiproxy.yml): use PROXY + TARGET_SERVICE +
# FAULT_NAME. slow_db is TT's headline fault - one target, ~all-DB-services blast, a trace blind
# spot (mysql uninstrumented) that only the kernel can attribute.
_DB_BLAST='["mysql","ts-auth-service","ts-user-service","ts-travel-service","ts-order-service","ts-route-service","ts-train-service","ts-price-service","ts-station-service","ts-payment-service","ts-inside-payment-service","ts-gateway-service","ts-ui-dashboard"]'
PXY[slow_db]=mysql; TSVC[slow_db]=mysql; FNAME[slow_db]=slow_db_mysql
BLAST[slow_db]="$_DB_BLAST"; MODALITY[slow_db]=kernel; TRACEVIS[slow_db]=blind_spot
PXY[error_storm]=mysql; TSVC[error_storm]=mysql; FNAME[error_storm]=error_storm_mysql
BLAST[error_storm]="$_DB_BLAST"; MODALITY[error_storm]=logs; TRACEVIS[error_storm]=covered

# --- the matrix (46 runs, matching the Sock Shop campaign) ------------------
# v2: the matrix lives in ONE file, sourced by both application drivers. v1 had two drivers
# with two different matrices - 8 of 12 families here, 11 of 12 on the other application - and
# that, not any deliberate choice, is why the stored run counts came out uneven.
source "$SD/../microservice-lttng-data-collection-scripts/campaign_matrix.sh"
# The shared collection tooling lives in the Sock Shop scripts dir. Derived from THIS
# script's location rather than an env var: STRATA_REPO is not set here, and an unset
# variable would have made SDD an absolute path to a directory that does not exist.
SDD="$(cd "$TTD/../microservice-lttng-data-collection-scripts" && pwd)"
build_matrix "trainticket"

echo "=== Train Ticket Phase-2 campaign: ${#MATRIX[@]} runs "\
"(baseline ${BASELINE_S}s / injection ${INJECTION_S}s / recovery ${RECOVERY_S}s) ==="
echo "    (slow_db + error_storm need the stack deployed WITH docker-compose.toxiproxy.yml)"
[[ ! -f "$MANIFEST" ]] && echo "run_id,recipe,intensity,workload,repeat,target,verification,event_loss,timestamp_utc" > "$MANIFEST"

idx=0
for entry in "${MATRIX[@]}"; do
    idx=$((idx + 1))
    read -r recipe intensity workload repeat <<< "$entry"
    [[ -n "$ONLY" && "$recipe" != "$ONLY" ]] && continue

    RUN="tt_${recipe}_${intensity}_${workload}_r${repeat}"
    RUN_DIR="$HOME/traces/${recipe}/${RUN}"
    # Resumable: a finished run may already sit in the archive, so check both.
    if [[ -f "$RUN_DIR/meta/runinfo_end.txt" ]] || \
       [[ -f "${ARCHIVE_DIR:-/mnt/archive/runs}/${recipe}/${RUN}/meta/runinfo_end.txt" ]]; then
        echo "[$idx/${#MATRIX[@]}] SKIP $RUN (already collected)"; continue
    fi
    if [[ "$workload" == "burst" ]]; then USERS="$USERS_BURST"; else USERS="$USERS_STEADY"; fi

    # per-fault target + ground-truth annotations (empty for host-scoped anomalies -> defaults)
    tsvc="${TARGET[$recipe]:-}"
    disp_target="${tsvc:-${TSVC[$recipe]:-host}}"   # svc-fault target, else DB proxy target, else host
    echo "[$idx/${#MATRIX[@]}] RUN  $RUN  (users=$USERS target=$disp_target)"
    if [[ "$DRY" -eq 1 ]]; then continue; fi

    env ${EXTRAENV[$recipe]:-} \
    PROFILE="$workload" \
    TARGET_SVC="$tsvc" \
    PROXY="${PXY[$recipe]:-}" \
    TARGET_SERVICE="${TSVC[$recipe]:-}" \
    FAULT_NAME="${FNAME[$recipe]:-}" \
    EXPECTED_BLAST_RADIUS="${BLAST[$recipe]:-}" \
    EXPECTED_WINNING_MODALITY="${MODALITY[$recipe]:-}" \
    TARGET_TRACE_VISIBILITY="${TRACEVIS[$recipe]:-}" \
        bash "$TTD/run_scenario_tt.sh" "$recipe" "$intensity" "$RUN" "$USERS" \
        > "$HOME/${RUN}.log" 2>&1 || echo "[$idx] WARN: run_scenario_tt returned nonzero for $RUN"

    # Package, record event loss, move off the collection disk - the SAME step the Sock Shop
    # driver runs. This driver previously only gzipped: no MANIFEST.json, no checksums, no
    # usable/not verdict and no event-loss record, so Train Ticket runs would have arrived
    # materially poorer than Sock Shop ones - the same silent divergence that gave v1 two
    # different fault matrices.
    loss=$(bash "$SDD/campaign_finish_run.sh" "$RUN_DIR" "$RUN" | tail -1)

    ARCHIVED="${ARCHIVE_DIR:-/mnt/archive/runs}/${recipe}/${RUN}"
    verdict="n/a"
    for d in "$RUN_DIR" "$ARCHIVED"; do
        if [[ -f "$d/verification.json" ]]; then
            verdict=$(python3 -c "import json;print(json.load(open('$d/verification.json')).get('verification_status','n/a'))" 2>/dev/null || echo n/a)
            break
        fi
    done
    echo "${RUN},${recipe},${intensity},${workload},${repeat},${disp_target},${verdict},${loss},$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFEST"
    echo "[$idx/${#MATRIX[@]}] DONE $RUN -> verification=$verdict"
done

echo
echo "=== TT campaign summary ($MANIFEST) ==="
if [[ "$DRY" -eq 0 ]]; then
    echo "runs by verification verdict:"; tail -n +2 "$MANIFEST" | cut -d, -f7 | sort | uniq -c
fi
echo "=== done ==="
