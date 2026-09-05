#!/bin/bash
# Fault recipe: Nagle + delayed ACK (co-located workload container).
#
# Two sensible TCP features that are pathological together: the sender holds a small write
# until the previous data is ACKed (Nagle), while the receiver holds the ACK for up to ~40 ms
# hoping to piggyback it on a reply (delayed ACK). A write-write-read exchange - a small header
# then a small body - stalls for a fixed ~40 ms every time.
#
# WHY THIS IS THE HARDEST CASE IN THE WHOLE MATRIX. Every signal we collect says the system is
# healthy: CPU idle, disk idle, no packets lost, no retransmissions, the application returning
# 200s. There is simply nothing to blame. An agent hunting for a saturated resource will not
# find one - which is exactly the shape Naser asked for, where the agent alone fails and a
# blueprint should win.
#
# THE TELL IS CLUSTERING, NOT MAGNITUDE. A queue or a slow dependency produces a SPREAD of
# latencies. This produces a SPIKE at one value, because the stall is a fixed timer rather
# than a queue. That is what a blueprint keys on, and it is why the workload also runs an
# identical control exchange with TCP_NODELAY set - the trace then contains the healthy and
# the stalled version of the same conversation, so the comparison is internal to one run.
#
# Pre-registered expectations: KERNEL only. Spans would show slow calls if the app did this,
# but the workload is synthetic, so nothing above the kernel sees it at all.
#
# Usage:
#   ./nagle_delayed_ack.sh inject [subtle|aggressive]
#   ./nagle_delayed_ack.sh cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="I_configuration"
FAULT_NAME="nagle_delayed_ack"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"the affected connections only\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="set TCP_NODELAY, or combine the header and body into one write"

CONTAINER="nagle-delayed-ack"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     CONNS="${CONNS:-2}" CPUS="${CPUS:-0.5}" ;;
      aggressive) CONNS="${CONNS:-8}" CPUS="${CPUS:-1.0}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # Loopback inside the container: the stall is a property of the TCP state machine, not of
    # the physical path, so it reproduces without touching the application network.
    workload_start "$CONTAINER" nagle_delayed_ack.py "$CPUS" -- "$CONNS" 100000
    gt_begin "$INTENSITY" "{\"connections\": $CONNS, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"expected_stall_ms\": 40, \"control\": \"identical exchange with TCP_NODELAY runs alongside\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
