#!/bin/bash
# Fault recipe: Nagle + delayed ACK (co-located workload container).
#
# Two sensible TCP features that are pathological together: the sender holds a small write
# until the previous data is ACKed (Nagle), while the receiver holds the ACK hoping to piggyback
# it on a reply (delayed ACK). A write-write-read exchange - a small header then a small body -
# stalls on a fixed timer every time.
#
# THE STALL HERE IS ~100 ms, NOT THE 40 ms THE TEXTBOOK QUOTES. Measured on the collection VM:
# median 99.48 ms, p95 100.66 ms over the smoke run. The 40 ms figure is the classic BSD
# delayed-ACK timer; Linux uses a quantised minimum RTO instead, and on the loopback-speed paths
# inside a Docker bridge it lands at ~100 ms. Written down because the number is what a
# blueprint would key on, and quoting 40 ms from memory would have put a wrong threshold into
# the dataset. The magnitude is platform-dependent - the CLUSTERING is not, which is the
# property below and the one worth keying on.
#
# WHY THIS IS THE HARDEST CASE IN THE WHOLE MATRIX. Every signal we collect says the system is
# healthy: CPU idle, disk idle, no packets lost, no retransmissions, the application returning
# 200s. There is simply nothing to blame. An agent hunting for a saturated resource will not
# find one - which is exactly the shape Naser asked for, where the agent alone fails and a
# blueprint should win.
#
# THE TELL IS CLUSTERING, NOT MAGNITUDE. A queue or a slow dependency produces a SPREAD of
# latencies. This produces a SPIKE at one value, because the stall is a fixed timer rather
# than a queue. Measured: median 99.48 ms against p95 100.66 ms - barely 1 ms of spread across
# the whole distribution, which no queue can produce. That is what a blueprint keys on, and it is why the workload also runs an
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
    gt_begin "$INTENSITY" "{\"connections\": $CONNS, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"expected_stall_ms\": 100, \"expected_stall_note\": \"measured on the collection VM: median 99.48 / p95 100.66; Linux minimum RTO, not the textbook 40 ms BSD delayed-ACK timer\", \"control\": \"identical exchange with TCP_NODELAY runs alongside\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
