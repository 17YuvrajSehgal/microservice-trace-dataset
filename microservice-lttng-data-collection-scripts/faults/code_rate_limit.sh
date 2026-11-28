#!/bin/bash
# Code defect (v6, group 8): a rate limit on one service's list path (catalogue, Go)
#
# The catalogue's list path accepts at most N requests per second and answers the rest at once with 429 Too Many
# Requests, before any work is done. The flag carries N (rate_limit:N).
#
# WHY THIS ONE. Errors with nothing slow behind them. error_storm fails on a broken database connection
# after the work started; here the service refuses at the door, fast, and only above a rate.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v7), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# MEASURED 28-11-2026 (check run r1): most failures are NOT the 429s. The catalogue's own circuit
# breaker on the list path (stock gobreaker: opens after 5 failures in a row, stays open 30 s)
# counts the 429s as failures and opens, and then every list request fails at once with 500
# ("circuit breaker is open"). r1 had 4,191 of those and 27 rate-limit rejections. The breaker is
# Sock Shop's own code and is left as it is: a limit that trips a breaker is a real cascade.
# Built by faults/code-defects/build_defect_images.sh (v6 images, 28-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS E11): the KERNEL shows the catalogue answering part of its list requests at once with a short
# answer and no database call; METRICS show catalogue 429s and an unchanged or lower answer time; LOGS may show nothing.
#
# Usage:
#   ./code_rate_limit.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_rate_limit"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="raise the limit, or make the caller back off and retry later"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-rate_limit:8}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v7}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="at most N list requests per second; the rest are answered at once with 429"
DEFECT_FIX="raise the limit, or make the caller back off and retry later"
DEFECT_PAIRS_WITH="error_storm"

code_defect_dispatch "$@"
