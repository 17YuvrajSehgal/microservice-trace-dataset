#!/bin/bash
# THE campaign matrix. Sourced by both application drivers so they cannot drift apart.
#
# WHY THIS FILE EXISTS
# --------------------
# v1 had two drivers with two different matrices, and neither covered every family:
#
#   run_campaign.sh     (Sock Shop)    CORE_FAULTS had  8 of 12
#   run_campaign_tt.sh  (Train Ticket) CORE_FAULTS had 11 of 12
#
# That is exactly why the stored run counts are uneven - Sock Shop ended with 50 runs and
# Train Ticket with 43, and the difference was never a deliberate choice. Defining the matrix
# once removes the whole class of problem.
#
# WHAT CHANGED FOR v2
# -------------------
#   * all 12 fault families in the core group, on both applications
#   * repeats 3 -> 5. v1's thinnest family had TWO runs and now carries a blueprint
#     threshold; five is the cheapest insurance available against that.
#   * the intensity and workload groups are the same on both applications
#
# ONE FAMILY CANNOT BE IDENTICAL, and it is recorded rather than hidden:
#   `queue_backlog` pauses the sole consumer of a message queue. Train Ticket has NO message
#   broker - its booking path is synchronous REST (see train-ticket-collection-scripts/
#   FAULTS-TT.md). The planned analogue is MySQL connection-pool exhaustion via a toxiproxy
#   connection cap, and that recipe has never been written. Until it is, TT_EXCLUDE keeps the
#   family out of the Train Ticket matrix explicitly, so the gap is a stated decision instead
#   of a silent omission.

# every fault recipe in faults/
CAMPAIGN_CORE_FAULTS=(anomaly_cpu anomaly_disk anomaly_mem anomaly_net dependency_outage
                      error_storm noisy_neighbor queue_backlog slow_db svc_cpu_cap
                      svc_mem_cap svc_net)

# faults whose subtle variant is worth having: the ones where intensity changed the answer in
# v1, plus the two memory families, whose thresholds are the thinnest in the library
CAMPAIGN_INTENSITY_FAULTS=(noisy_neighbor slow_db svc_cpu_cap svc_mem_cap anomaly_mem)

# faults worth seeing under a bursty workload rather than steady load
CAMPAIGN_WORKLOAD_FAULTS=(slow_db error_storm anomaly_net)

CAMPAIGN_REPEATS="${CAMPAIGN_REPEATS:-5}"
CAMPAIGN_REPEATS_VARIANT="${CAMPAIGN_REPEATS_VARIANT:-3}"

# families that cannot run on a given app, with the reason.
#
# CLARIFIED 4 Sept: this does NOT drop queue_backlog from the dataset. Sock Shop CAN run it -
# it has RabbitMQ and a single-consumer queue - so the family is collected there in full. It
# is Train Ticket that has no message broker. The two applications are simply asymmetric on
# this one family, and that asymmetry is stated at build time rather than being a silent hole.
#
# `conn_pool_exhaustion` (proposed for v2) is the closer analogue and would give Train Ticket
# a saturation fault of its own - see FAULT-CATEGORIES-V2.md.
CAMPAIGN_TT_EXCLUDE=(queue_backlog)

# --- v2 CANDIDATE FAMILIES (see FAULT-CATEGORIES-V2.md) ----------------------------------
# Naser, 4 Sept: "latency is only the first step. we will cover around 10 different issue
# types." Our 12 families sit in 5 categories and are nearly all "slow because a resource is
# scarce". These ten add concurrency, resource leaks, security/abuse and configuration.
#
# INTENTIONALLY EMPTY until each recipe exists in faults/ AND has passed a pilot smoke run.
# On a campaign we cannot repeat, an untested recipe is a worse risk than a missing family -
# so a name only moves into this array once it has been shown to actually inject.
CAMPAIGN_NEW_FAULTS=()
# candidates, in the order they should be written:
#   concurrency   lock_contention priority_inversion deadlock
#   leaks         fd_exhaustion conn_pool_exhaustion
#   security      resource_abuse data_exfiltration fork_storm
#   config        dns_delay nagle_delayed_ack

# build_matrix <app>   ->  fills the array MATRIX with "recipe intensity workload repeat"
build_matrix() {
    local app="${1:-sockshop}" f r excluded
    MATRIX=()

    for r in $(seq 1 "$CAMPAIGN_REPEATS"); do MATRIX+=("normal none steady $r"); done
    for r in $(seq 1 "$CAMPAIGN_REPEATS"); do MATRIX+=("normal none burst $r"); done

    for f in "${CAMPAIGN_CORE_FAULTS[@]}" ${CAMPAIGN_NEW_FAULTS[@]+"${CAMPAIGN_NEW_FAULTS[@]}"}; do
        excluded=0
        if [[ "$app" == "trainticket" ]]; then
            for x in "${CAMPAIGN_TT_EXCLUDE[@]}"; do
                [[ "$f" == "$x" ]] && excluded=1
            done
        fi
        if [[ "$excluded" -eq 1 ]]; then
            echo "[matrix] SKIP $f on $app - no equivalent in this application," \
                 "see FAULTS-TT.md" >&2
            continue
        fi
        for r in $(seq 1 "$CAMPAIGN_REPEATS"); do MATRIX+=("$f aggressive steady $r"); done
    done

    for f in "${CAMPAIGN_INTENSITY_FAULTS[@]}"; do
        for r in $(seq 1 "$CAMPAIGN_REPEATS_VARIANT"); do MATRIX+=("$f subtle steady $r"); done
    done

    for f in "${CAMPAIGN_WORKLOAD_FAULTS[@]}"; do
        for r in $(seq 1 "$CAMPAIGN_REPEATS_VARIANT"); do MATRIX+=("$f aggressive burst $r"); done
    done
}

# print_matrix_summary <app>
print_matrix_summary() {
    local app="${1:-sockshop}"
    build_matrix "$app"
    echo "=== matrix for $app: ${#MATRIX[@]} runs ==="
    printf '%s\n' "${MATRIX[@]}" | awk '{print $1}' | sort | uniq -c | sort -rn
}
