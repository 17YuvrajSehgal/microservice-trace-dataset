#!/bin/bash
# Fault recipe: dependency outage (docker pause of one service).
#
# Freezes the target's processes (SIGSTOP semantics via the freezer cgroup):
# the container stays "up" but stops answering - callers hit connect/read
# timeouts, exercising their retry and error paths. Default target: payment
# (on the checkout critical path; orders is the first-hop victim).
#
# Pre-registered expectations (see faults/README.md): TRACES localize
# (spans at orders pointing at payment); LOGS carry the exception detail.
# In the KERNEL view the paused cgroup is conspicuous silence.
#
# Usage:
#   TARGET_SVC=payment ./dependency_outage.sh inject
#   TARGET_SVC=payment ./dependency_outage.sh cleanup
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-payment}"
FAULT_FAMILY="D_dependency"
FAULT_NAME="dependency_outage_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"orders\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-traces}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="docker unpause the target container"

CONTAINER="$(resolve_container "$TARGET_SVC")"

case "${1:-}" in
  inject)
    # Single intensity: paused is paused.
    docker pause "$CONTAINER" > /dev/null
    gt_begin "aggressive" "{\"mechanism\": \"docker pause (freezer cgroup)\", \"container\": \"$CONTAINER\"}"
    ;;
  cleanup)
    docker unpause "$CONTAINER" > /dev/null || true
    gt_end
    ;;
  status)
    docker inspect -f '{{.Name}} Paused={{.State.Paused}}' "$CONTAINER"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject | cleanup | status"; exit 1 ;;
esac
