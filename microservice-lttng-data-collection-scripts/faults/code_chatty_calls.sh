#!/bin/bash
# Code defect (v4, group 5): three extra identical calls to a service for every request (front-end, Node)
#
# For every request the front-end forwards, it also makes three more identical calls to the same service and throws
# their answers away. Calls between the front-end and each service rise four times; the answers are the same.
#
# WHY THIS ONE. More calls between two services for the same work. code_n_plus_one (v2) is service to
# database; this is service to service, on every path at once.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (frontend-bugs:v4), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v4 images, 27-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F6): SPANS show four client calls to the same service per request; the KERNEL shows four times
# the connections and requests between the front-end and each service; METRICS show the callee's rate up four times.
#
# Usage:
#   ./code_chatty_calls.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_chatty_calls"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="make one call per request and reuse its answer"

DEFECT_SERVICE="front-end"
DEFECT_BUG="${DEFECT_BUG:-chatty_calls}"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v4}"
DEFECT_CMD=""
DEFECT_MECHANISM="three extra identical calls per forwarded request, answers discarded"
DEFECT_FIX="make one call per request and reuse its answer"
DEFECT_PAIRS_WITH="code_n_plus_one"

code_defect_dispatch "$@"
