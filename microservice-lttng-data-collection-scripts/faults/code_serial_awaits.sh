#!/bin/bash
# Code defect: work done one at a time that was meant to be parallel (front-end).
#
# WHY THIS ONE. Another way to look like a slow dependency while every dependency is fast. The distinguishing feature should be that the total scales with item COUNT rather than with any per-call latency - whether that is visible in kernel data is exactly the question.
#
# HOW IT IS INJECTED. Not by swapping in a different image per defect. Every defect lives in
# ONE image per service, gated at runtime on the STRATA_BUG environment variable, so the
# control is the SAME BINARY with the defect switched off. A patched image is not the stock
# image - different build, different layer - so if the control were the stock service, every
# comparison would measure the rebuild as well as the defect.
#
# Run `code_serial_awaits.sh control` for that paired healthy run. It is not a `normal` run and
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
#   ./code_serial_awaits.sh inject [subtle|aggressive]
#   ./code_serial_awaits.sh control | cleanup | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_serial_awaits"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="issue the requests concurrently and await them together"

DEFECT_SERVICE="front-end"
DEFECT_BUG="serial_awaits"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v2}"
DEFECT_CMD=""
DEFECT_MECHANISM="the handler waits for each downstream step in turn instead of issuing them together, so latency grows linearly with the number of items"
DEFECT_FIX="issue the requests concurrently and await them together"
DEFECT_PAIRS_WITH="slow_db"

code_defect_dispatch "$@"
