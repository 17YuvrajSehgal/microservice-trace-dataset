#!/bin/bash
# Fault recipe: the connection-tracking table of the host is full (nf_conntrack_max).
#
# The kernel keeps one entry per connection that crosses the host's packet filter (Docker's
# bridge and NAT use it for every container connection). When the table is full, the first
# packet of a NEW connection is dropped; connections that already have an entry keep working.
# This is what a default table size does on a busy host: old sessions are fine, new ones hang
# and are retried, and the only message is one kernel log line.
#
# WHY THIS FAMILY. conn_pool_exhaustion is a limit inside one client. port_exhaustion is a
# limit in one container. Here the limit is in the host's packet path and hits whoever opens a
# connection next, whichever service that is.
#
# Host-wide and risky for the operator: a new SSH connection to the VM is a new connection too.
# The recipe therefore never needs a new connection itself, and cleanup is a local sysctl.
# Restart-free. Cleanup writes the old value back and reads it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D7): the KERNEL shows SYNs sent and
# retransmitted with no answer, from several sources, while established connections carry
# traffic normally; the kernel log has "nf_conntrack: table full, dropping packet"; METRICS
# and what users see depend on how many new connections this application opens at steady load
# - measured in the calibration, not assumed.
#
# Usage:
#   ./conntrack_full.sh inject [subtle|aggressive] | cleanup | status
#   env: HEADROOM  entries allowed above the current count (default 0 aggressive, 50 subtle)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="E_infrastructure"
FAULT_NAME="conntrack_full"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"any service that opens a new connection\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="raise net.netfilter.nf_conntrack_max"

ORIG_FILE="$FAULT_STATE_DIR/${FAULT_NAME}.orig_max"
cmax() { cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null | tr -d '\n'; }
ccount() { cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) HEADROOM="${HEADROOM:-0}" ;;
      subtle)     HEADROOM="${HEADROOM:-50}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    BEFORE="$(cmax)"; CUR="$(ccount)"
    [[ -n "$BEFORE" && -n "$CUR" ]] || { echo "[$FAULT_NAME] connection tracking is not loaded on this host"; exit 1; }
    mkdir -p "$FAULT_STATE_DIR"; echo "$BEFORE" > "$ORIG_FILE"
    LIMIT=$(( CUR + HEADROOM ))
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"nf_conntrack_max\": $LIMIT, \"nf_conntrack_max_before\": $BEFORE, \"entries_at_injection\": $CUR, \"headroom\": $HEADROOM}"
    echo "$LIMIT" | sudo tee /proc/sys/net/netfilter/nf_conntrack_max > /dev/null
    echo "[$FAULT_NAME] nf_conntrack_max $BEFORE -> $(cmax) (entries now $(ccount))"
    ;;
  cleanup)
    ORIG="$(cat "$ORIG_FILE" 2>/dev/null || echo 262144)"
    echo "$ORIG" | sudo tee /proc/sys/net/netfilter/nf_conntrack_max > /dev/null
    NOW="$(cmax)"
    [[ "$NOW" == "$ORIG" ]] || echo "[$FAULT_NAME] WARN: nf_conntrack_max is '$NOW', wanted '$ORIG'"
    echo "[$FAULT_NAME] nf_conntrack_max restored to $NOW (entries now $(ccount)); kernel log 'table full' lines since boot: $(sudo dmesg 2>/dev/null | grep -c 'nf_conntrack: table full' || true)"
    gt_end
    ;;
  status)
    echo "nf_conntrack_max=$(cmax) entries=$(ccount)"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
