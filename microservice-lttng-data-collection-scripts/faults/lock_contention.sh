#!/bin/bash
# Fault recipe: user-level lock contention (co-located workload container).
#
# Many threads fighting over one briefly-held lock. CPython's threading.Lock is a real futex
# on Linux, and we record every syscall, so the waits land in the trace directly.
#
# WHY THIS FAMILY EXISTS. Naser asked for lock contention by name. Finding F22 measured total
# futex wait across all 13 v1 families and found it FLAT (largest move 1.38x on one
# application, 1.11x on the other), so the negative control was already in hand before this
# recipe existed - the reverse of the F17 mistake, where a signal was checked on 8 of 13
# families and the one skipped beat every network fault.
#
# What was missing was a POSITIVE example, which is what this produces.
#
# THE SHAPE, NOT THE TOTAL. F22 also settled how a lock blueprint must NOT be written. On the
# first probe total futex wait was 408 seconds per second of wall clock, and `java` alone
# waited 6,684 s over 22,036 calls - about 300 ms each. That is thread pools parked waiting
# for work, not contention. Contention is the opposite shape: MANY waits, each SHORT.
#
# NOTE ON SCOPE. Naser asked for KERNEL lock contention. Measured on the v2 VM: there are ZERO
# `lock_*` tracepoints, because stock Ubuntu kernels do not build in the lock debugging they
# need. So this is user-level locking via futex, and the blueprint must say so. Not a large
# loss - application locks are where service latency actually comes from.
#
# Pre-registered expectations: KERNEL only. The workload emits no spans, no service logs and
# no service metrics; cadvisor shows a new container to anyone who thinks to look.
#
# Usage:
#   ./lock_contention.sh inject [subtle|aggressive]
#   ./lock_contention.sh cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="F_concurrency"
FAULT_NAME="lock_contention"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"all services (mild)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="remove the contending workload; in real code, shorten the critical section"

CONTAINER="lock-contention"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      # More threads and a longer hold means more waiters per release, so the wait RATE rises
      # while each wait stays short - which is the shape we want to be measuring.
      subtle)     THREADS="${THREADS:-6}"  HOLD_US="${HOLD_US:-100}" WORK_US="${WORK_US:-200}" CPUS="${CPUS:-1.0}" ;;
      aggressive) THREADS="${THREADS:-16}" HOLD_US="${HOLD_US:-200}" WORK_US="${WORK_US:-50}"  CPUS="${CPUS:-2.0}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    workload_start "$CONTAINER" lock_contention.py "$CPUS" -- "$THREADS" "$HOLD_US" "$WORK_US"
    gt_begin "$INTENSITY" "{\"threads\": $THREADS, \"hold_us\": $HOLD_US, \"work_us\": $WORK_US, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"lock_type\": \"user-level futex\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
