#!/bin/bash
# Code defect: a mutex held across a database round trip (catalogue).
#
# WHY THIS ONE. The single most common real concurrency bug in service code, and the honest counterpart to the synthetic lock_contention recipe. Same symptom - threads serialised on a lock - from a completely different cause, and with a completely different fix. If a blueprint cannot separate them, the honest verdict is "threads are serialised on a lock, and kernel data cannot tell you whether that is contention or a coding mistake", which is a useful limit rather than a failure.
#
# HOW IT IS INJECTED. Not by swapping in a different image per defect. Every defect lives in
# ONE image per service, gated at runtime on the STRATA_BUG environment variable, so the
# control is the SAME BINARY with the defect switched off. A patched image is not the stock
# image - different build, different layer - so if the control were the stock service, every
# comparison would measure the rebuild as well as the defect.
#
# Run `code_lock_across_io.sh control` for that paired healthy run. It is not a `normal` run and
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
#   ./code_lock_across_io.sh inject [subtle|aggressive]
#   ./code_lock_across_io.sh control | cleanup | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_lock_across_io"
FAULT_SCOPE="service"
TARGET_SERVICE="catalogue"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"catalogue\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="release the lock before the query; it only guards the in-memory state"

DEFECT_SERVICE="catalogue"
DEFECT_BUG="lock_across_io"
DEFECT_IMAGE="${DEFECT_IMAGE:-catalogue-bugs:v2}"
DEFECT_CMD="/app -port=80"
DEFECT_MECHANISM="the lock is taken before the query and released after it, so every request serialises behind one mutex"
DEFECT_FIX="release the lock before the query; it only guards the in-memory state"
DEFECT_PAIRS_WITH="lock_contention"

code_defect_dispatch "$@"
