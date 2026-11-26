#!/bin/bash
# Code defect (v3, group 2): a busy-wait inside a request handler (catalogue, Go)
#
# Every list request spins on the CPU for 15 ms before it answers. The loop reads the clock through the vDSO, so it
# makes no system call. Go serves other requests on other threads, so nothing stops: requests are slower and the
# service uses more CPU.
#
# WHY THIS ONE. The counterpart of code_event_loop_block: CPU burned on the request path, but in a
# multi-threaded runtime, so the service slows instead of stopping. A blueprint must tell the two apart.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v3), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v3 images, 26-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS A4): the KERNEL shows the catalogue's threads on the CPU in long runs with no system calls between
# them, and its CPU use up; METRICS show its answer time up by about the spin; nothing fails.
#
# Usage:
#   ./code_spin_loop.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_spin_loop"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove the busy-wait; wait on an event or a timer instead of spinning"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-spin_loop}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v3}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="a busy-wait of 15 ms on the list path; the thread stays on the CPU and makes no system call"
DEFECT_FIX="remove the busy-wait; wait on an event or a timer instead of spinning"
DEFECT_PAIRS_WITH="svc_cpu_cap"

code_defect_dispatch "$@"
