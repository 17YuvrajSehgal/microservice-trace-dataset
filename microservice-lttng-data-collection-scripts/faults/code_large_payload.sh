#!/bin/bash
# Code defect (v3, group 2): answers far larger than needed (catalogue, Go)
#
# Every list answer carries 16 kB of padding per item, about 15 times its normal size. The number of calls is
# the same; the bytes per call are not.
#
# WHY THIS ONE. The only defect here whose mark is the SIZE of the data, not time, errors or CPU. Its
# lookalike is data_exfiltration (bytes going out), but here the bytes go to the normal caller.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (catalogue-bugs:v3), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v3 images, 26-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F5): the KERNEL shows the catalogue sending many more bytes per answer to the front-end; spans the
# same count with longer answers; METRICS show network bytes up.
#
# Usage:
#   ./code_large_payload.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_large_payload"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="return only the fields the caller needs, and page large results"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="${DEFECT_BUG:-large_payload}"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v3}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="16 kB of padding is added to every item of the list answer; the caller needs none of it"
DEFECT_FIX="return only the fields the caller needs, and page large results"
DEFECT_PAIRS_WITH="data_exfiltration"

code_defect_dispatch "$@"
