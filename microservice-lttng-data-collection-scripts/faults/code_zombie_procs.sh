#!/bin/bash
# Code defect (v4, group 5): child processes that are never collected (catalogue, Go)
#
# Every 10th list request starts a short child process and never waits for it. Each child ends at once and stays
# in the process table as a zombie until the service itself ends (disarm, after tracing).
#
# WHY THIS ONE. Processes that exit and are never reaped: the process table grows with dead entries. Unlike
# fork_storm the rate is low; unlike thread_leak the entries are dead processes.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v4), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v4 images, 27-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS H3): the KERNEL shows one process forking and exec-ing a child at a steady rate, every child exiting
# and none of them reaped (no wait); METRICS barely move.
#
# Usage:
#   ./code_zombie_procs.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_zombie_procs"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="wait for every child you start (cmd.Wait), or use a helper that reaps them"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-zombie_procs}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v4}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="every 10th list request starts a child process and never calls Wait, so each child stays a zombie"
DEFECT_FIX="wait for every child you start (cmd.Wait), or use a helper that reaps them"
DEFECT_PAIRS_WITH="fork_storm"

code_defect_dispatch "$@"
