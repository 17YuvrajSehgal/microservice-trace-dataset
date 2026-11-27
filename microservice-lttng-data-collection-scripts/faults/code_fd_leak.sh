#!/bin/bash
# Code defect (v4, group 5): a file descriptor that is opened and never closed (catalogue, Go)
#
# Every 10th list request opens a file and keeps it open for good. The process's descriptor count only grows,
# by a few per second; nothing fails until the descriptor limit is reached, far beyond one run.
#
# WHY THIS ONE. A slow leak of a kernel resource where nothing is wrong yet. fd_exhaustion (v2) is the
# end state, all descriptors gone at once; this is the slow climb before it.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v4), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v4 images, 27-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F3): the KERNEL shows one process opening a file (openat) at a steady rate and never closing it;
# METRICS show the process's open descriptors growing; nothing else moves.
#
# Usage:
#   ./code_fd_leak.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_fd_leak"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\\"catalogue\\", \\"its callers\\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="close every file you open (defer f.Close()); do not keep handles in a global list"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-fd_leak}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v4}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="every 10th list request opens a file and keeps a reference to it, so it is never closed"
DEFECT_FIX="close every file you open (defer f.Close()); do not keep handles in a global list"
DEFECT_PAIRS_WITH="fd_exhaustion"

code_defect_dispatch "$@"
