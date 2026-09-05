#!/bin/bash
# Fault recipe: rapid BOUNDED process creation (co-located workload container).
#
# NOT a fork bomb. A fork bomb is unbounded and recursive and would take the machine down;
# this runs beside a live application for 120 s. The number of live children is capped, each
# child exits on its own, and the container carries a hard PID limit as a second guard. If the
# cap is reached the loop waits instead of spawning.
#
# WHY IT EARNS A FAMILY. `sched_process_fork` is unmistakable and nothing else in our dataset
# produces it in volume, which makes this the cheapest possible POSITIVE CONTROL for the whole
# scheduler pipeline: if a blueprint cannot see this one, the problem is in our analysis
# rather than in the fault.
#
# It is also a real production shape. A crash-looping container, a runaway supervisor, or a
# shell script spawning a process per item all look like this - and all are usually diagnosed
# late, because no resource is saturated in an obvious way.
#
# Naser, 2 Sept: "Mainly performance, but security can be a part of it as well."
#
# Pre-registered expectations: KERNEL only. cadvisor shows a rising process count to anyone
# who thinks to look.
#
# Usage:
#   ./fork_storm.sh inject [subtle|aggressive]
#   ./fork_storm.sh cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="H_security"
FAULT_NAME="fork_storm"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host scheduler\", \"all services (mild)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="stop the spawning process; a PID limit on the cgroup contains the blast radius"

CONTAINER="fork-storm"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      subtle)     RATE="${RATE:-20}"  LIVE="${LIVE:-80}"  LIFE="${LIFE:-2}" PIDS="${PIDS:-256}" CPUS="${CPUS:-0.5}" ;;
      aggressive) RATE="${RATE:-100}" LIVE="${LIVE:-300}" LIFE="${LIFE:-2}" PIDS="${PIDS:-512}" CPUS="${CPUS:-1.0}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    # --pids-limit is the hard stop. Even if the workload's own cap were wrong, the kernel
    # refuses the fork rather than letting it run away - which matters for something spawning
    # processes next to a live application.
    workload_start "$CONTAINER" fork_storm.py "$CPUS" \
        --pids-limit "$PIDS" -- "$RATE" "$LIVE" "$LIFE"
    gt_begin "$INTENSITY" "{\"spawns_per_s\": $RATE, \"max_live\": $LIVE, \"child_lifetime_s\": $LIFE, \"pids_limit\": $PIDS, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"note\": \"bounded and PID-capped; not a fork bomb\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
