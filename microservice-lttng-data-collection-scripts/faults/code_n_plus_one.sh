#!/bin/bash
# Code defect: one extra query per returned row (catalogue).
#
# WHY THIS ONE. Looks exactly like a slow datastore, and the datastore is perfectly healthy - it is answering every query quickly, there are simply far too many of them. One is the database's fault and one is the caller's, and the evidence a caller sees is nearly identical.
#
# HOW IT IS INJECTED. Not by swapping in a different image per defect. Every defect lives in
# ONE image per service, gated at runtime on the STRATA_BUG environment variable, so the
# control is the SAME BINARY with the defect switched off. A patched image is not the stock
# image - different build, different layer - so if the control were the stock service, every
# comparison would measure the rebuild as well as the defect.
#
# Run `code_n_plus_one.sh control` for that paired healthy run. It is not a `normal` run and
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
#   ./code_n_plus_one.sh inject [subtle|aggressive]
#   ./code_n_plus_one.sh control | cleanup | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_n_plus_one"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="fetch the rows in the original query, or batch the follow-up into one IN clause"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="n_plus_one"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v2}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="after the list query, the handler issues a further query for every row it returned, so database work grows with result size"
DEFECT_FIX="fetch the rows in the original query, or batch the follow-up into one IN clause"
DEFECT_PAIRS_WITH="slow_db"

code_defect_dispatch "$@"
