#!/bin/bash
# Code defect (v3, group 2): a thread that is started and never ends (catalogue, Go)
#
# Every 10th list request starts a goroutine that locks itself to an OS thread and blocks forever, so each one keeps
# an OS thread. The thread count of the process only grows while the defect is on, and does NOT come down after it
# is switched off: the leaked threads stay until the process restarts (disarm, after tracing).
#
# WHY THIS ONE. A leak of a kernel resource that is not memory and not files: one process's thread count
# only grows, with nothing failing until a limit is reached.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v3), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v3 images, 26-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F2): the KERNEL shows one process creating threads (clone) at a steady rate, none of them
# exiting; METRICS barely move; nothing fails within the run.
#
# Usage:
#   ./code_thread_leak.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_thread_leak"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="do not lock goroutines to threads; give every started thread a way to finish"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-thread_leak}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v3}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="every 10th list request starts a goroutine locked to an OS thread that blocks forever; the thread is never released"
DEFECT_FIX="do not lock goroutines to threads; give every started thread a way to finish"
DEFECT_PAIRS_WITH="fork_storm"

code_defect_dispatch "$@"
