#!/bin/bash
# Code defect (v3, group 2): a regular expression that takes exponential time on some inputs (front-end, Node)
#
# On a small share of requests the front-end tests a nested-quantifier pattern on an input that almost matches.
# V8's backtracking engine takes exponential time on it. Node has one thread, so while it runs the WHOLE front-end
# stops; between such requests it is normal. The flag carries the input length and the share (N:P).
#
# WHY THIS ONE. Irregular stalls of one single-threaded service, against code_event_loop_block where
# every request blocks it. Same thread, same kind of work, a different pattern in time.
#
# HOW IT IS INJECTED. Like every code defect here: one image per service (frontend-bugs:v3), the defect
# switched on at run time through the flag file /dev/shm/strata_bug, so the baseline and the
# control are the SAME binary with the defect off. `arm` (before tracing) puts the service on
# that image with the defect off; `inject` writes the flag; `cleanup` writes "none".
# Built by faults/code-defects/build_defect_images.sh (v3 images, 26-11-2026).
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS F4): the KERNEL shows the front-end's thread on the CPU for long single stretches at irregular times,
# with all its requests waiting during them; METRICS show its p95 up and its p50 almost unchanged.
#
# Usage:
#   ./code_regex_backtrack.sh arm | inject [subtle|aggressive] | cleanup | disarm | control | status
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"
source "$_SD/code_defect_lib.sh"

FAULT_FAMILY="J_code_defect"
FAULT_NAME="code_regex_backtrack"
FAULT_SCOPE="service"
TARGET_SERVICE="front-end"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"front-end\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="rewrite the pattern without nested quantifiers, or bound the input length"

DEFECT_SERVICE="front-end"
DEFECT_BUG="${DEFECT_BUG:-regex_backtrack:26:0.002}"
DEFECT_IMAGE="${DEFECT_IMAGE:-frontend-bugs:v3}"
DEFECT_CMD=""
DEFECT_MECHANISM="a nested-quantifier regular expression on an almost-matching input, on a small share of requests; it backtracks for hundreds of milliseconds on the only thread"
DEFECT_FIX="rewrite the pattern without nested quantifiers, or bound the input length"
DEFECT_PAIRS_WITH="code_event_loop_block"

code_defect_dispatch "$@"
