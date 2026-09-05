#!/bin/bash
# Fault recipe: deadlock (co-located workload container).
#
# Two locks, two threads, opposite acquisition order. A fresh pair deadlocks every few seconds,
# so the number of permanently blocked threads GROWS through the injection window instead of
# being one event at the start - that gives the trace a gradient to measure.
#
# WHY IT IS A SEPARATE FAMILY FROM lock_contention. Both block threads on a lock, so both show
# futex waits. The difference is the ending:
#
#     lock_contention   many waits, each SHORT     - the holder always releases
#     deadlock          few waits, each INFINITE   - the holder never releases
#
# That makes deadlock the closer look-alike of `dependency_outage`: both stop serving and go
# quiet. The distinction worth measuring is that deadlocked threads still exist and are
# genuinely blocked INSIDE a syscall, whereas a paused container has threads that are simply
# never scheduled. Findings F11-F13 showed the paused container is invisible in the scheduler
# stream; a deadlock should not be, because the threads sit in futex.
#
# If that holds, it is a discriminator we do not currently have. If it does not, it is a real
# negative result about the limits of kernel-only diagnosis. Both outcomes are worth having.
#
# Pre-registered expectations: KERNEL only.
#
# Usage:
#   ./deadlock.sh inject [subtle|aggressive]
#   ./deadlock.sh cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="F_concurrency"
FAULT_NAME="deadlock"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"the deadlocked workload only\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="a consistent lock ordering; a deadlock cannot be unwedged at runtime"

CONTAINER="deadlock"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     RESPAWN="${RESPAWN:-10}" PAIRS="${PAIRS:-6}"  CPUS="${CPUS:-0.5}" ;;
      aggressive) RESPAWN="${RESPAWN:-5}"  PAIRS="${PAIRS:-12}" CPUS="${CPUS:-0.5}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    workload_start "$CONTAINER" deadlock.py "$CPUS" -- "$RESPAWN" "$PAIRS"
    gt_begin "$INTENSITY" "{\"respawn_s\": $RESPAWN, \"max_pairs\": $PAIRS, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"mechanism\": \"AB-BA lock ordering\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
