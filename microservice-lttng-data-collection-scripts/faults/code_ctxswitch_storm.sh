#!/bin/bash
# Code defect (v5, group 6): a pool of far too many threads that wake up all the time (catalogue, Go)
#
# The first list request starts a pool of N threads. Each one sleeps a few milliseconds, wakes up, does nothing and
# sleeps again. Every wake-up is a context switch. The threads end when the flag changes. The flag carries the pool
# size and the sleep in microseconds (N:US).
#
# WHY THIS ONE. Scheduler work with almost no CPU use per thread. code_thread_leak has many threads that
# are all asleep; code_spin_loop has one thread that never sleeps. This is many threads with very short runs.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v5), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v5 images, 27-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS A3): the KERNEL shows a very high sched_switch rate for one process, spread over hundreds of
# threads with very short runs; METRICS show the container's CPU up a little and its thread count up; answer times
# are measured in the calibration, not assumed.
#
# Usage:
#   ./code_ctxswitch_storm.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_ctxswitch_storm"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="size thread pools to the number of cores; do not poll with short sleeps, wait on an event"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-ctxswitch_storm:400:5000}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v5}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="a pool of N OS threads that each sleep US microseconds in a loop; started by the first list request, ends when the flag changes"
DEFECT_FIX="size thread pools to the number of cores; do not poll with short sleeps, wait on an event"
DEFECT_PAIRS_WITH="code_thread_leak"

code_defect_dispatch "$@"
