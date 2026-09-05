#!/bin/bash
# Fault recipe: priority inversion (co-located workload container).
#
# A low-priority thread holds a lock, a high-priority thread waits for it, and medium-priority
# threads hog the CPU so the holder never runs to release it. The highest-priority work is
# blocked, indirectly, by work it never interacts with.
#
# WHY THIS ONE MATTERS MOST. Naser: a blueprint has to earn its place on HARD problems, and
# this is the hardest shape we can inject - nothing looks saturated in an interesting way. CPU
# is busy, but with middle-priority work behaving perfectly normally. Disk idle. Network idle.
# The lock is held by a thread that is not running. Nothing points at the real culprit.
#
# An agent with no blueprint has no reason to guess this, which is exactly the case where a
# blueprint should win.
#
# NOT REAL-TIME PRIORITIES, ON PURPOSE. The textbook demonstration uses SCHED_FIFO. A spinning
# real-time thread can make a machine unresponsive, and this runs unattended for 120 s beside a
# live application. nice-based inversion is weaker but has the same structure, and the CPU cap
# on the container is a second guard.
#
# Pre-registered expectations: KERNEL only. sched_switch should show the low-priority holder
# runnable but rarely on-CPU; futex should show FEW waits, each LONG - the opposite of
# lock_contention, and that contrast is the discriminator between the two.
#
# Usage:
#   ./priority_inversion.sh inject [subtle|aggressive]
#   ./priority_inversion.sh cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="F_concurrency"
FAULT_NAME="priority_inversion"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"the high-priority path only\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="priority inheritance on the lock, or do not hold it across scheduling boundaries"

CONTAINER="priority-inversion"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     MID="${MID:-3}" HOLD_MS="${HOLD_MS:-20}" CPUS="${CPUS:-1.0}" ;;
      aggressive) MID="${MID:-6}" HOLD_MS="${HOLD_MS:-50}" CPUS="${CPUS:-2.0}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # SYS_NICE lets the high-priority thread actually raise itself. The workload degrades
    # gracefully without it, so this is best-effort rather than required.
    workload_start "$CONTAINER" priority_inversion.py "$CPUS" \
        --cap-add=SYS_NICE -- "$MID" "$HOLD_MS"
    gt_begin "$INTENSITY" "{\"mid_threads\": $MID, \"hold_ms\": $HOLD_MS, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"mechanism\": \"nice-based inversion, not SCHED_FIFO\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
