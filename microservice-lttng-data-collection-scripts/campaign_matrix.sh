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
#
# `dns_delay` added 5 Sept, MEASURED not assumed. Six Train Ticket containers - ui-dashboard,
# gateway, travel, order, basic, station - were instrumented with a counting iptables rule and
# sent ZERO DNS packets across 600 requests. TT resolves peers through Nacos over HTTP, so name
# resolution is simply not in its request path. Sock Shop, by contrast, sends 54 packets per 400
# requests to Docker's embedded resolver.
#
# So this is not a recipe that needs fixing - it is an architectural difference, and it is a
# result worth reporting: DNS faults are meaningless on discovery-service architectures. Running
# it on TT would produce 5 runs labelled as a fault that provably did nothing.
#
# The equal-counts fix, if we want one, is a TT-native member of the same family: impair NACOS
# (netem or toxiproxy in front of it) so discovery is slow there in the way DNS is slow here.
# Not written yet - see progress-notes/04-09-2026.
CAMPAIGN_TT_EXCLUDE=(queue_backlog dns_delay)

# --- v2 CANDIDATE FAMILIES (see FAULT-CATEGORIES-V2.md) ----------------------------------
# Naser, 4 Sept: "latency is only the first step. we will cover around 10 different issue
# types." Our 12 families sit in 5 categories and are nearly all "slow because a resource is
# scarce". These ten add concurrency, resource leaks, security/abuse and configuration.
#
# VERIFIED 5 Sept on BOTH applications: 10/10 pass on stratatrace-ss and on stratatrace-tt,
# each with a 10/10 negative control (every check run with nothing injected must FAIL - two of
# them used to pass vacuously).
#
# Running them on Train Ticket was not a formality. Three recipes behaved differently there, and
# every time the cause was a constant measured on Sock Shop:
#
#   fd_exhaustion         21 idle descriptors there, 125 here - a fixed nofile=64 kills the JVM
#   conn_pool_exhaustion  MySQL 5.7 stops at 151, MySQL 8 allows 2000; the holder's own
#                         nofile=1024 capped it at 1020 and left the server 39% free
#   dns_delay             52 -> 2555 ms there, 58 -> 62-167 ms here; a 300 ms threshold failed
#                         a fault that was working
#
# All three now derive their numbers from the system at inject time.
#
# Worth carrying into the analysis: fd_exhaustion produces OPPOSITE application symptoms on the
# two apps. Node queues in the listen backlog and slows (p50 28 ms, 0 errors); the Spring
# gateway fails outright (p50 15,673 ms, 357 of 600 requests failed). Same injection, same
# measured mechanism.
CAMPAIGN_NEW_FAULTS=(lock_contention priority_inversion deadlock fd_exhaustion
                     conn_pool_exhaustion resource_abuse data_exfiltration fork_storm
                     dns_delay nagle_delayed_ack)
# candidates, in the order they should be written:
#   concurrency   lock_contention priority_inversion deadlock
#   leaks         fd_exhaustion conn_pool_exhaustion
#   security      resource_abuse data_exfiltration fork_storm
#   config        dns_delay nagle_delayed_ack

# --- CODE DEFECTS (see CODE-BUGS-V2.md) --------------------------------------------------
# Every fault above is EXTERNAL to the application: we throttle a cgroup, delay a packet,
# pause a container. The code is innocent and the environment is made hostile. Real incidents
# are usually the reverse. These inject the defect into the service itself.
#
# Feasible because we already build two Sock Shop services from our own forks - a bug is one
# more branch and one more image tag, on a pipeline we proved when adding OpenTelemetry.
#
# Each one PAIRS with an environment fault we already have, and the pairing is the experiment:
# the same symptom, once from the environment and once from the code. If the kernel signatures
# turn out identical, that is a result too - the honest verdict becomes "threads are serialised
# on a lock, and kernel data cannot tell you whether that is contention or a coding mistake".
#
#   code_lock_across_io    (Go)    pairs with lock_contention
#   code_n_plus_one        (Go)    pairs with slow_db
#   code_event_loop_block  (Node)  pairs with svc_cpu_cap
#   code_serial_awaits     (Node)  pairs with slow_db
#   code_unbounded_cache   (Node)  pairs with svc_mem_cap
#
# VERIFIED 5 Sept on stratatrace-ss. Each one builds, starts, serves traffic, and measurably
# misbehaves against its OWN control - the same image with STRATA_BUG=none, so the comparison
# isolates the defect rather than the rebuild:
#
#   code_lock_across_io     5.14x slower  (7 -> 36 ms median, concurrency 60)
#   code_n_plus_one         6.14x slower  (7 -> 43 ms)
#   code_event_loop_block  39.98x slower  (93 -> 3718 ms)
#   code_serial_awaits     16.41x slower  (95 -> 1559 ms)
#   code_unbounded_cache    memory, not latency - growth is the signal, measured in the run
#
# Single-app: the defect lives in one service's source, so a code bug is 5 runs, not 10.
CAMPAIGN_CODE_BUGS=(code_lock_across_io code_n_plus_one code_event_loop_block
                    code_serial_awaits code_unbounded_cache)

# build_matrix <app>   ->  fills the array MATRIX with "recipe intensity workload repeat"
build_matrix() {
    local app="${1:-sockshop}" f r excluded
    MATRIX=()

    for r in $(seq 1 "$CAMPAIGN_REPEATS"); do MATRIX+=("normal none steady $r"); done
    for r in $(seq 1 "$CAMPAIGN_REPEATS"); do MATRIX+=("normal none burst $r"); done

    # Code defects live in a SPECIFIC service's source, so they are single-application. The
    # five recommended ones patch Sock Shop's Go catalogue and Node front-end; the Java
    # equivalents for Train Ticket are listed in CODE-BUGS-V2.md but not built yet.
    local codebugs=()
    if [[ "$app" == "sockshop" ]]; then
        codebugs=(${CAMPAIGN_CODE_BUGS[@]+"${CAMPAIGN_CODE_BUGS[@]}"})
    elif [[ ${#CAMPAIGN_CODE_BUGS[@]} -gt 0 ]]; then
        echo "[matrix] SKIP ${#CAMPAIGN_CODE_BUGS[@]} code defects on $app -"              "they patch Sock Shop services; see CODE-BUGS-V2.md" >&2
    fi

    for f in "${CAMPAIGN_CORE_FAULTS[@]}" ${CAMPAIGN_NEW_FAULTS[@]+"${CAMPAIGN_NEW_FAULTS[@]}"}              ${codebugs[@]+"${codebugs[@]}"}; do
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
