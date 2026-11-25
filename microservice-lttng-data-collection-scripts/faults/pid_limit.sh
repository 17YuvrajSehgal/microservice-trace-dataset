#!/bin/bash
# Fault recipe: a service hits its process/thread limit (cgroup pids.max via docker update).
#
# A container may be limited in how many tasks (processes and threads) it has. When the limit
# is at or just above what the service already uses, every attempt to start one more thread
# fails with EAGAIN. Nothing is slow and nothing is killed; the service just cannot grow, so
# work that needs a new thread fails or waits.
#
# WHY THIS FAMILY. It is a third "limit reached" fault next to fd_exhaustion (EMFILE on open and
# socket) and port_exhaustion (EADDRNOTAVAIL on connect): the same shape - one error return in
# one process - on a different system call (clone) and a different limit. A Java service
# reports it as "unable to create new native thread", which reads like a memory problem.
#
# Restart-free: docker update writes pids.max of the running container. Cleanup removes the
# limit and reads pids.max back.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS H2): the KERNEL shows clone() returning
# -11 (EAGAIN) in one container and its thread count flat at the limit; LOGS carry the
# runtime's error string; what users see depends on whether the service needs new threads
# under this load - measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=orders ./pid_limit.sh inject [subtle|aggressive] | cleanup | status
#   env: HEADROOM  tasks allowed above the current count (default 0 aggressive, 8 subtle)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

# orders, not carts. Measured 25-11-2026 by limiting each service to its current task count for
# 15 s under the 150-user load: orders had 282 thread creations refused (about 19 per second, it
# starts a thread per request); rabbitmq 2; carts, shipping, queue-master, user, payment,
# catalogue, front-end, edge-router and both databases 0. A service with a warm, fixed thread
# pool never asks for a new thread, so this limit cannot touch it.
TARGET_SVC="${TARGET_SVC:-orders}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="pid_limit_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="raise or remove the task limit (docker update --pids-limit -1)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
# Read the cgroup from the HOST. `docker exec` needs a new process inside the container, which
# is exactly what the limit refuses: with the limit on, the read itself failed with EAGAIN.
CG="/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "$CONTAINER" 2>/dev/null).scope"
cg() { cat "$CG/$1" 2>/dev/null | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) HEADROOM="${HEADROOM:-0}" ;;
      subtle)     HEADROOM="${HEADROOM:-8}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # The LOWEST of 10 readings over one second, not one reading. The count flickers by one
    # when a short-lived thread exists. Measured on the 5 collected runs (25-11-2026): runs 1-3
    # read 67 and got a limit of 67; runs 4 and 5 read 68 at that instant, got 68, and so had
    # one thread of headroom - about half as many refused thread creations (267-314 per 20 s
    # against 441-610) with the same user-visible errors.
    CUR=""; for _ in 1 2 3 4 5 6 7 8 9 10; do
        c="$(cg pids.current)"
        if [[ -n "$c" ]] && [[ -z "$CUR" || "$c" -lt "$CUR" ]]; then CUR="$c"; fi
        sleep 0.1
    done
    BEFORE="$(cg pids.max)"
    [[ -n "$CUR" ]] || { echo "[$FAULT_NAME] cannot read pids.current of $CONTAINER"; exit 1; }
    LIMIT=$(( CUR + HEADROOM ))
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"pids_limit\": $LIMIT, \"tasks_at_injection\": $CUR, \"headroom\": $HEADROOM, \"pids_max_before\": \"$BEFORE\", \"container\": \"$CONTAINER\"}"
    docker update --pids-limit "$LIMIT" "$CONTAINER" > /dev/null
    echo "[$FAULT_NAME] pids.max $BEFORE -> $(cg pids.max) (tasks now $(cg pids.current))"
    ;;
  cleanup)
    docker update --pids-limit -1 "$CONTAINER" > /dev/null
    NOW="$(cg pids.max)"
    [[ "$NOW" == "max" ]] || echo "[$FAULT_NAME] WARN: the limit was not removed, pids.max is '$NOW'"
    echo "[$FAULT_NAME] pids.max restored to $NOW (tasks now $(cg pids.current))"
    gt_end
    ;;
  status)
    echo "$CONTAINER pids.max=$(cg pids.max) pids.current=$(cg pids.current)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
