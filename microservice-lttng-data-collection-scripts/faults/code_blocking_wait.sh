#!/bin/bash
# Code defect (v4, group 5): a blocking wait on the only thread of a Node service (front-end)
#
# On a small share of requests the front-end's single thread blocks in a synchronous wait (a futex sleep) for some
# milliseconds. The thread is OFF the CPU, but nothing else can run in the service meanwhile. The flag carries the
# wait and the share (MS:P).
#
# WHY THIS ONE. The single thread stops while sleeping, not while computing. event_loop_block and
# regex_backtrack stop it ON the CPU; a blueprint must tell these apart.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (frontend-bugs:v4), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v4 images, 27-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F8): the KERNEL shows the front-end's main thread asleep in a futex wait for tens of milliseconds,
# with requests waiting meanwhile and no CPU used; METRICS show its p95 up and its p50 almost unchanged.
#
# Usage:
#   ./code_blocking_wait.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_blocking_wait"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\\"front-end\\", \\"its callers\\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="never block the event loop; use the asynchronous form (await a timer or a promise)"

DEFECT_SERVICE="front-end"
DEFECT_BUG="${DEFECT_BUG:-blocking_wait:30:0.02}"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v4}"
DEFECT_CMD=""
DEFECT_MECHANISM="a synchronous wait (Atomics.wait) on the request path, on a share of requests; the only thread sleeps and nothing else runs"
DEFECT_FIX="never block the event loop; use the asynchronous form (await a timer or a promise)"
DEFECT_PAIRS_WITH="code_event_loop_block"

code_defect_dispatch "$@"
