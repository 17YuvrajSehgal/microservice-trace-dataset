#!/bin/bash
# Fault recipe: slow DNS resolution (host-level packet loss on port 53 only).
#
# Drops a fraction of outbound DNS queries, so resolution retries and every new connection
# stalls before it can even start. Nothing is broken - the resolver is simply unreliable.
#
# WHY IT PAIRS WITH slow_db. Both look like "waiting on the network before work starts", and
# the evidence a caller sees is nearly identical: a socket call that takes a long time. The
# difference is WHERE the wait happens - before `connect` for DNS, after it for a slow
# datastore. If a blueprint cannot separate those, that is worth knowing, because the fixes
# have nothing in common.
#
# MECHANISM. iptables with a statistic match, dropping a proportion of outbound UDP/53. A
# dropped query is retried by the resolver after a fixed timeout, so the visible effect is
# occasional multi-second stalls rather than uniform slowness - which is what a flaky resolver
# actually looks like.
#
# HOW BIG THE STALL IS VARIES ENORMOUSLY, AND WE DO NOT FULLY KNOW WHY.
#
#     Sock Shop    front-end            52 ms -> 2555 ms   (twice)
#     Train Ticket ts-gateway-service   58 ms ->   62-167 ms  (57 queries dropped)
#     Sock Shop    front-end, later     53 ms ->     57 ms    (23 queries dropped)
#
# The third reading is the important one. It is the SAME host and the SAME container that gave
# 2555 ms earlier, so the difference cannot be the container's resolver configuration - which is
# what I first wrote down after seeing only the first two rows. Resolver cache state is the
# likely driver: a warm cache answers locally and generates few upstream queries to drop.
#
# Recorded as unresolved rather than explained away. What IS dependable across all three
# readings is that queries are being dropped, which is why the check keys on the rule's packet
# counter rather than on a latency threshold.
#
# CONSEQUENCE FOR THE DATASET, and it is a large one: this fault may have little or no
# application-level signature in our deployments, because inter-service traffic resolves through
# Docker's embedded DNS and is untouched (see below). That would make it a genuine hard case -
# loud in the kernel, quiet everywhere else - but it must be LABELLED that way rather than
# presented as a latency fault. Measure the application impact before drawing the conclusion.
#
# WHAT IT ACTUALLY HITS - MEASURED, and narrower than the name suggests.
#
# On the collection VM, from inside an application container:
#
#     external name (example.com)     52 ms  ->  2555 ms      (49x)
#     internal name (catalogue)       52 ms  ->    50 ms      (unchanged)
#
# Container-to-container names are answered by Docker's embedded resolver inside the container
# network namespace and never leave as a UDP/53 packet, so the rule cannot see them. Only
# lookups that go UPSTREAM are affected.
#
# This matters for what the fault means. It is NOT "service discovery is broken" - inter-service
# resolution is untouched. It is "anything reaching outside the cluster stalls", which is the
# realistic shape of a flaky upstream resolver. A blueprint that read this as service discovery
# failing would be keying on something that did not happen.
#
# It also affects the HOST, not just containers: during the window `sudo` itself logged
# "unable to resolve host ... Temporary failure in name resolution". Harmless, and worth knowing
# when reading anything else the host does inside the injection window.
#
# SAFETY. The rule is scoped to UDP port 53 and is removed in cleanup by exact match, so it
# cannot outlive the run or affect anything else. It is inserted at the TOP of OUTPUT and
# deleted by the same specification, so a partial cleanup is not possible - either the rule is
# there or it is not. Docker and package tooling can be affected during the window, which is
# expected and is the point.
#
# Pre-registered expectations: KERNEL (socket calls stall before connect) and TRACES if the
# application resolves names during the window. Metrics see raised latency with no CPU, disk
# or error correlate.
#
# Usage:
#   ./dns_delay.sh inject [subtle|aggressive]
#   ./dns_delay.sh prove | cleanup | status
#     prove = time real lookups from inside a container and report external vs internal
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="I_configuration"
FAULT_NAME="dns_delay"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"any service resolving a name\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="fix or replace the resolver; cache resolutions; use IPs for internal service calls"

# Kept in one place so inject and cleanup cannot drift apart.
rule_args() { echo "OUTPUT -p udp --dport 53 -m statistic --mode random --probability $1 -j DROP"; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     PROB="${PROB:-0.25}" ;;
      aggressive) PROB="${PROB:-0.60}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # shellcheck disable=SC2046
    sudo iptables -I $(rule_args "$PROB")
    gt_begin "$INTENSITY" "{\"drop_probability\": $PROB, \"protocol\": \"udp\", \"port\": 53, \"mechanism\": \"iptables statistic random drop\"}"
    ;;
  cleanup)
    # Delete by exact specification, for every probability we might have used, so cleanup is
    # correct even if the recipe is re-run or interrupted between intensities.
    for p in 0.25 0.60 "${PROB:-0.60}"; do
        # shellcheck disable=SC2046
        sudo iptables -D $(rule_args "$p") 2>/dev/null || true
    done
    gt_end
    ;;
  prove)
    # Measure the delay, do not just confirm our own rule is loaded.
    #
    # "the iptables rule is present" is evidence about what WE did, not about what the system
    # does - the same mistake that let conn_pool_exhaustion pass while occupying nothing. So
    # time real lookups, and time an internal name too, because the difference between the two
    # is the honest description of this fault's reach.
    C="$(resolve_container "${PROBE_SVC:-front-end}")"
    if [[ "${STRATA_APP:-sockshop}" == "trainticket" ]]; then
        C="$(resolve_container "${PROBE_SVC:-ts-gateway-service}")"
        INTERNAL="${PROBE_INTERNAL:-ts-order-service}"
    else
        INTERNAL="${PROBE_INTERNAL:-catalogue}"
    fi
    median_ms() {   # median_ms <name> - 5 lookups from inside the container
        local n="$1" i s e
        for i in 1 2 3 4 5; do
            s=$(date +%s%N)
            docker exec "$C" getent hosts "$n" >/dev/null 2>&1 || true
            e=$(date +%s%N)
            echo $(( (e - s) / 1000000 ))
        done | sort -n | sed -n 3p
    }
    # THE DECISIVE EVIDENCE IS THE RULE'S OWN PACKET COUNTER, not a latency threshold.
    #
    # Measured: the same fault costs 2555 ms on Sock Shop and 62-167 ms on Train Ticket. Both
    # are working - the TT rule dropped 57 packets during five lookups. The difference is the
    # container's resolv.conf: Sock Shop's walks three search domains before trying the name
    # absolutely, so one lookup becomes many queries and many chances to be dropped, while the
    # gateway image sets ndots:0 and asks once.
    #
    # So the magnitude belongs to the IMAGE, not to the fault, and a fixed 300 ms threshold
    # would have declared a working fault dead on Train Ticket - which is exactly what it did.
    # The counter rising while a container resolves proves the fault is in the path of real DNS
    # traffic, on any application.
    drops() { sudo iptables -L OUTPUT -v -n -x 2>/dev/null | awk '/udp dpt:53/{print $1; exit}'; }
    D0="$(drops)"
    EXT="$(median_ms "${PROBE_EXTERNAL:-example.com}")"
    INT="$(median_ms "$INTERNAL")"
    D1="$(drops)"
    DROPPED=$(( ${D1:-0} - ${D0:-0} ))
    echo "external ${EXT} ms, internal ${INT} ms, queries dropped during the probe: ${DROPPED}"
    [[ "$DROPPED" -gt 0 ]]
    ;;
  status)
    sudo iptables -S OUTPUT | grep -- "--dport 53" || echo "no dns rule active"
    ;;
  *) echo "usage: $0 inject [subtle|aggressive] | prove | cleanup | status"; exit 1 ;;
esac
