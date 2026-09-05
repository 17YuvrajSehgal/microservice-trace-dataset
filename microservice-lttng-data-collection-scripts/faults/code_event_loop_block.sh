#!/bin/bash
# Code defect: synchronous CPU work inside a request handler (front-end).
#
# WHY THIS ONE. Nothing else in the dataset produces this shape. The service stalls ENTIRELY - including requests that never touch the slow path - because a single-threaded runtime has nothing left to run them on. It resembles a CPU quota from the outside, but a quota you can raise and this you must rewrite.
#
# HOW IT IS INJECTED. Not by swapping in a different image per defect. Every defect lives in
# ONE image per service, gated at runtime on the STRATA_BUG environment variable, so the
# control is the SAME BINARY with the defect switched off. A patched image is not the stock
# image - different build, different layer - so if the control were the stock service, every
# comparison would measure the rebuild as well as the defect.
#
# Run `code_event_loop_block.sh control` for that paired healthy run. It is not a `normal` run and
# should not be labelled as one: it is this image with the defect disabled.
#
# BEFORE FIRST USE the image must exist and have been verified:
#     bash faults/code-defects/build_defect_images.sh
#
# Pre-registered expectations: KERNEL. Ground truth carries the commit, the
# mechanism and the CORRECT FIX - the last of which no infrastructure fault can give us,
# because "raise the quota" is the only possible answer there.
#
# Usage:
#   ./code_event_loop_block.sh inject [subtle|aggressive]
#   ./code_event_loop_block.sh control | cleanup | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_event_loop_block"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="move the work to a worker thread, or use the asynchronous form"

DEFECT_SERVICE="front-end"
DEFECT_BUG="event_loop_block"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v2}"
DEFECT_CMD=""
DEFECT_MECHANISM="a synchronous key-derivation call runs on the request path; Node has one thread, so the whole service stops for its duration"
DEFECT_FIX="move the work to a worker thread, or use the asynchronous form"
DEFECT_PAIRS_WITH="svc_cpu_cap"

code_defect_dispatch "$@"
