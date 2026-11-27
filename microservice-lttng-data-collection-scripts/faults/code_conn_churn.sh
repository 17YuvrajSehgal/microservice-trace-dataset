#!/bin/bash
# Code defect (v5, group 6): keep-alive switched off: a new connection for every call (front-end, Node)
#
# The front-end's calls to a service no longer reuse connections: each call opens a new TCP connection and closes
# it after one answer. The number of calls and the answers are unchanged.
#
# WHY THIS ONE. One connection per request with no errors. error_storm opens connections that are reset;
# code_chatty_calls makes more calls. Here the calls are the same and only the connection handling changed.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (frontend-bugs:v5), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v5 images, 27-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D6): the KERNEL shows one TCP handshake and one close per call between the front-end and the
# service, where the baseline has almost none; SPANS and METRICS show the same number of calls, a little slower.
#
# Usage:
#   ./code_conn_churn.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_conn_churn"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="keep connections alive and reuse them (the default agent); do not send Connection: close"

DEFECT_SERVICE="front-end"
DEFECT_BUG="${DEFECT_BUG:-conn_churn}"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v5}"
DEFECT_CMD=""
DEFECT_MECHANISM="the request option forever=false and the header Connection: close on every call to the service"
DEFECT_FIX="keep connections alive and reuse them (the default agent); do not send Connection: close"
DEFECT_PAIRS_WITH="error_storm"

code_defect_dispatch "$@"
