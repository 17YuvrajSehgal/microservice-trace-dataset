#!/bin/bash
# Code defect (v6, group 8): an in-process queue that only grows (front-end, Node)
#
# Every call the front-end makes to a service goes into an in-process queue, and one worker takes R calls per
# second from it. When more calls arrive than R the queue only grows: memory grows and each call waits longer than
# the one before. The flag carries R (unbounded_queue:R).
#
# WHY THIS ONE. Latency that grows steadily through the window, with the service idle. code_unbounded_cache
# grows memory with no slowdown; event_loop_block stops the thread on the CPU; here the thread is mostly idle.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (frontend-bugs:v6), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v6 images, 28-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F7): METRICS show the front-end's memory and answer time rising together through the window;
# the KERNEL shows the front-end's main thread waking every 10 ms and mostly idle, and its calls to services
# leaving at a steady pace; SPANS show the front-end's server spans growing while its client spans stay short.
#
# Usage:
#   ./code_unbounded_queue.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_unbounded_queue"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="bound the queue and reject or shed load when it is full; size the worker to the arrival rate"

DEFECT_SERVICE="front-end"
DEFECT_BUG="${DEFECT_BUG:-unbounded_queue:200}"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v6}"
DEFECT_CMD=""
DEFECT_MECHANISM="calls to services go into a queue served at R per second; above R the queue only grows"
DEFECT_FIX="bound the queue and reject or shed load when it is full; size the worker to the arrival rate"
DEFECT_PAIRS_WITH="code_unbounded_cache"

code_defect_dispatch "$@"
