#!/bin/bash
# Fault recipe: unreliable name resolution for ONE service.
#
# Drops a fraction of the target service's DNS queries, so resolution retries and the
# occasional new connection stalls before it can start. Nothing is broken - the resolver is
# simply unreliable.
#
# THE FIRST VERSION WAS NEARLY INERT, AND MEASUREMENT IS THE ONLY REASON WE KNOW
# -----------------------------------------------------------------------------
# It put the rule in the HOST's OUTPUT chain. That catches lookups leaving the machine, and our
# applications almost never make one - they talk to each other by service name, which Docker's
# embedded resolver answers inside the container's own network namespace.
#
# Measured on Sock Shop under load, host-level rule:
#
#     baseline   p50 67.7 / 80.8 ms
#     during     p50 85.2 / 81.0 ms      <- noise
#     dropped    11 packets in the whole probe
#
# Ten campaign runs of that would have been ten runs of a configuration fault that changed
# nothing. It passed its smoke test the whole time, because the check asked whether the rule
# existed rather than whether anything happened.
#
# WHERE THE FAULT ACTUALLY LIVES
# ------------------------------
# Inside the container's network namespace, aimed at the embedded resolver. Counted there, the
# application really does resolve: 54 DNS packets per 400 requests - infrequent, because
# connections are pooled, but not zero.
#
# Careful with the match. Docker DNATs 127.0.0.11:53 to a high port, and nat OUTPUT runs before
# filter OUTPUT, so a `--dport 53` rule in the container sees the REWRITTEN port and matches
# nothing at all. A first attempt read 0 packets and looked like proof the app never resolves.
# Match on the resolver's ADDRESS instead, which survives the rewrite.
#
# WHAT IT DOES, AND WHY IT IS A GOOD HARD CASE
# --------------------------------------------
#     baseline   p50 71.9   p95 201.7   wall    914 ms
#     during     p50 61.8   p95  78.7   wall 12,566 ms
#
# The median is fine. The p95 is fine. Wall-clock time is 15x. A few requests waited seconds on
# a retry while everything below p95 sailed through, so every summary statistic an operator
# would normally reach for says the system is healthy.
#
# That is the same shape as nagle_delayed_ack and the reason both are in the catalogue: faults
# whose evidence is invisible to the aggregate. Percentile dashboards cannot see this one.
#
# PAIRS WITH slow_db. Both look like "waiting on the network before work starts". The difference
# is WHERE the wait happens - before `connect` for DNS, after it for a slow datastore. If a
# blueprint cannot separate those, that is worth knowing, because the fixes have nothing in
# common.
#
# SAFETY. The rule lives in one container's namespace and is deleted by exact specification, so
# it cannot outlive the run or touch anything else. If the container is recreated the namespace
# goes with it, which removes the rule as a side effect.
#
# Pre-registered expectations: KERNEL (sendto/recvfrom on the resolver socket, retries, and the
# stalls before connect) and TRACES if the application resolves inside the window. Metrics see
# a raised tail with no CPU, disk or error correlate - and only if the tail is looked at.
#
# Usage:
#   ./dns_delay.sh inject [subtle|aggressive]
#   ./dns_delay.sh prove | cleanup | status
#   env: TARGET_SVC   (default: the app's front door)
#        STRATA_APP   sockshop | trainticket
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="I_configuration"
FAULT_NAME="dns_delay"
FAULT_SCOPE="service"
if [[ "${STRATA_APP:-sockshop}" == "trainticket" ]]; then
    TARGET_SVC="${TARGET_SVC:-ts-gateway-service}"
else
    TARGET_SVC="${TARGET_SVC:-front-end}"
fi
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"whatever it calls by name\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="fix or replace the resolver; cache resolutions; use IPs for internal service calls"

target_pid() {
    local c pid
    c="$(compose_container "$TARGET_SVC" 2>/dev/null || true)"
    [[ -z "$c" ]] && { echo "[$FAULT_NAME] cannot find a container for $TARGET_SVC" >&2; return 1; }
    pid="$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || true)"
    [[ -z "$pid" || "$pid" == "0" ]] && { echo "[$FAULT_NAME] $TARGET_SVC is not running" >&2; return 1; }
    echo "$pid"
}

# The resolver the container actually uses, read from its own resolv.conf rather than assumed
# to be 127.0.0.11 - a container on the default bridge gets the host's resolvers instead.
resolver_ip() {
    local c
    c="$(compose_container "$TARGET_SVC" 2>/dev/null || true)"
    docker exec "$c" awk '/^nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null || echo "127.0.0.11"
}

ns() { sudo nsenter -t "$1" -n "${@:2}"; }

# One place, so inject and cleanup cannot drift apart. Address, NOT --dport 53: Docker rewrites
# the port before the filter chain sees it (see the header).
rule_args() { echo "OUTPUT -d $1 -p udp -m statistic --mode random --probability $2 -j DROP"; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     PROB="${PROB:-0.25}" ;;
      aggressive) PROB="${PROB:-0.60}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    PID="$(target_pid)" || exit 1
    RESOLVER="$(resolver_ip)"
    # shellcheck disable=SC2046
    if ! ns "$PID" iptables -I $(rule_args "$RESOLVER" "$PROB"); then
        echo "[$FAULT_NAME] could not install the rule in $TARGET_SVC's namespace"
        exit 1
    fi
    echo "[$FAULT_NAME] dropping ${PROB} of $TARGET_SVC's queries to $RESOLVER"
    gt_begin "$INTENSITY" "{\"target_service\": \"$TARGET_SVC\", \"target_pid\": $PID, \"resolver\": \"$RESOLVER\", \"drop_probability\": $PROB, \"protocol\": \"udp\", \"mechanism\": \"iptables statistic random drop inside the service's network namespace, matched on the resolver address because Docker rewrites the port before the filter chain\"}"
    ;;

  prove)
    # THE PACKET COUNTER, not a latency threshold.
    #
    # Latency is the wrong thing to gate on here twice over. The size of the stall swung from
    # 2555 ms to 57 ms on the SAME host and container across runs, so any threshold is a coin
    # toss; and the application effect hides in wall-clock time while p50 and p95 stay healthy,
    # so the obvious statistics would report "no fault" on a fault that costs 15x.
    #
    # Packets dropped while the application runs is true on both applications and on every run.
    PID="$(target_pid)" || exit 1
    RESOLVER="$(resolver_ip)"
    drops() { ns "$PID" iptables -L OUTPUT -v -n -x 2>/dev/null | awk -v r="$RESOLVER" '$0 ~ r && /DROP/{print $1; exit}'; }
    D0="$(drops)"
    # Real application traffic, not synthetic lookups: the question is whether the fault is in
    # the path the application uses.
    if [[ "${STRATA_APP:-sockshop}" == "trainticket" ]]; then
        URL="${PROBE_URL:-http://localhost:8080/api/v1/travelservice/trips/left}"
    else
        URL="${PROBE_URL:-http://localhost:80/catalogue}"
    fi
    R="$(python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/code-defects/loadprobe.py" "$URL" "${PROBE_N:-400}" "${PROBE_CONC:-40}" 2>&1 | tr '\n' ' ')"
    D1="$(drops)"
    DROPPED=$(( ${D1:-0} - ${D0:-0} ))
    echo "queries dropped while the app ran: ${DROPPED} | ${R}"
    [[ "$DROPPED" -gt 0 ]]
    ;;

  cleanup)
    # Delete by exact specification, for every probability we might have used, so cleanup is
    # correct even if the recipe is re-run or interrupted between intensities. A container that
    # was recreated takes its namespace - and the rule - with it, so a miss here is not a leak.
    if PID="$(target_pid 2>/dev/null)"; then
        RESOLVER="$(resolver_ip)"
        for p in 0.25 0.60 "${PROB:-0.60}"; do
            # shellcheck disable=SC2046
            ns "$PID" iptables -D $(rule_args "$RESOLVER" "$p") 2>/dev/null || true
        done
        echo "[$FAULT_NAME] rules removed from $TARGET_SVC's namespace"
    else
        echo "[$FAULT_NAME] $TARGET_SVC not running - its namespace and the rule are gone with it"
    fi
    gt_end
    ;;

  status)
    if PID="$(target_pid 2>/dev/null)"; then
        ns "$PID" iptables -S OUTPUT 2>/dev/null | grep -- "-p udp" || echo "no dns rule active"
    else
        echo "$TARGET_SVC not running"
    fi
    ;;

  *) echo "usage: $0 inject [subtle|aggressive] | prove | cleanup | status"; exit 1 ;;
esac
