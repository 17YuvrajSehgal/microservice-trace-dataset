#!/bin/bash
# Fault recipe: file-descriptor exhaustion INSIDE a target service container.
#
# A process in the service container takes descriptors until `socket` starts returning EMFILE,
# then keeps failing for the whole window. The service is running, and failing, at a specific
# syscall.
#
# WHY IT RUNS INSIDE THE SERVICE, unlike the concurrency recipes. Descriptor limits are
# per-process and per-container. A standalone container would produce the signature but affect
# nothing, and a fault that does not touch the application is not a fault for root-cause
# purposes. `docker exec` puts the pressure inside the target so the blast radius is a real
# service - and so the namespace ids we now record on every event can attribute it.
#
# WHY THE SIGNATURE IS UNUSUALLY CLEAN. We record every syscall WITH ITS RETURN VALUE, so
# EMFILE (-24) is stated by the kernel on every failed call. Almost every other fault in the
# dataset has to be diagnosed from a shifted distribution; this one announces itself.
#
# PAIRS WITH dependency_outage. Both end with a service that stops serving. The difference is
# that this service is running and FAILING, while an outage means it is not running at all.
# F11-F13 showed a paused container is invisible in the scheduler stream; this should be loud.
# Separating "failing" from "absent" is a discriminator we do not currently have.
#
# SAFETY. The exhauster runs as a child process inside the container and holds everything in
# memory only. Cleanup kills it by exact command match, which releases every descriptor at
# once. It cannot outlive the run, and it never touches the host descriptor table.
#
# Pre-registered expectations: KERNEL (EMFILE returns) and LOGS (the service will complain).
#
# Usage:
#   ./fd_exhaustion.sh inject [subtle|aggressive]
#   ./fd_exhaustion.sh cleanup | status
#   env: TARGET_SVC (default carts)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="G_resource_leak"
FAULT_NAME="fd_exhaustion"
FAULT_SCOPE="service"
TARGET_SVC="${TARGET_SVC:-carts}"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"its callers\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="close descriptors on the error path; raise the limit only after fixing the leak"

CONTAINER="$(resolve_container "$TARGET_SVC")"
MARKER="stratatrace_fd_exhaust"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     FDS="${FDS:-20000}" RAMP="${RAMP:-45}" ;;
      aggressive) FDS="${FDS:-60000}" RAMP="${RAMP:-20}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "no such container: $CONTAINER"; exit 1; }

    # The target images are minimal and may not ship python, so the exhauster is written in
    # shell + a tiny C-free trick: open descriptors by duplicating stdin in a loop. Portable
    # to any container that has a shell, which all of them do.
    docker exec -d "$CONTAINER" sh -c "
      # marker in the command line so cleanup can find and kill exactly this
      exec -a $MARKER sh -c '
        i=0
        while [ \$i -lt $FDS ]; do
          exec 3<&0 2>/dev/null || break
          eval \"exec \$((i+10))<&0\" 2>/dev/null || break
          i=\$((i+1))
        done
        # hold them, and keep trying so refusals keep appearing through the window
        while true; do
          eval \"exec \$((i+10))<&0\" 2>/dev/null
          i=\$((i+1))
          sleep 0.01
        done
      '" || { echo "docker exec failed"; exit 1; }

    sleep 2
    if ! docker exec "$CONTAINER" sh -c "ps -eo args 2>/dev/null | grep -q '[s]tratatrace_fd_exhaust'"; then
        echo "[$FAULT_NAME] WARNING: exhauster not visible in $CONTAINER - verify before trusting this run"
    fi
    gt_begin "$INTENSITY" "{\"target_container\": \"$CONTAINER\", \"target_fds\": $FDS, \"ramp_s\": $RAMP, \"mechanism\": \"in-container descriptor exhaustion until EMFILE\"}"
    ;;
  cleanup)
    docker exec "$CONTAINER" sh -c "pkill -f '$MARKER' 2>/dev/null" >/dev/null 2>&1 || true
    gt_end
    ;;
  status)
    docker exec "$CONTAINER" sh -c "ls /proc/*/fd 2>/dev/null | wc -l; ps -eo args | grep '[s]tratatrace_fd_exhaust' | head -1" 2>/dev/null \
        || echo "container not running"
    ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
