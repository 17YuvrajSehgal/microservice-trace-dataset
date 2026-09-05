#!/bin/bash
# Code defect: a cache that is never evicted (front-end).
#
# WHY THIS ONE. The code version of svc_mem_cap, and the only GRADUAL fault in the whole matrix - everything else is a step change that is either off or on. It also gives us the memory_leak shape that was parked in future.md, without needing the longer run that a true leak would.
#
# HOW IT IS INJECTED. Not by swapping in a different image per defect. Every defect lives in
# ONE image per service, gated at runtime on the STRATA_BUG environment variable, so the
# control is the SAME BINARY with the defect switched off. A patched image is not the stock
# image - different build, different layer - so if the control were the stock service, every
# comparison would measure the rebuild as well as the defect.
#
# Run `code_unbounded_cache.sh control` for that paired healthy run. It is not a `normal` run and
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
#   ./code_unbounded_cache.sh inject [subtle|aggressive]
#   ./code_unbounded_cache.sh control | cleanup | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_unbounded_cache"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="bound the cache and evict; key it on something with a finite domain"

DEFECT_SERVICE="front-end"
DEFECT_BUG="unbounded_cache"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v2}"
DEFECT_CMD=""
DEFECT_MECHANISM="every request appends to an in-memory cache keyed on the request URL, and nothing ever removes an entry, so memory grows for as long as traffic arrives"
DEFECT_FIX="bound the cache and evict; key it on something with a finite domain"
DEFECT_PAIRS_WITH="svc_mem_cap"

code_defect_dispatch "$@"
