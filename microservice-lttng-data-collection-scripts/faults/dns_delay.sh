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
#   ./dns_delay.sh cleanup | status
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
  status)
    sudo iptables -S OUTPUT | grep -- "--dport 53" || echo "no dns rule active"
    ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
