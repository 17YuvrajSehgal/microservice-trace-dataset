#!/bin/bash
# Fault recipe: a service restricted to too few CPU cores (cpuset via docker update).
#
# One container may run on ONE core (aggressive) or TWO (subtle) while the other cores of the
# machine stay free. All of its threads - request threads, garbage collection, the JIT - then
# share that core and wait for each other.
#
# WHY THIS FAMILY. It is the look-alike of svc_cpu_cap: the same service gets slow for lack of
# CPU, with no error anywhere. The mechanism is different and so is the fix:
#   svc_cpu_cap   a quota per 100 ms period: the service is stopped and released on a fixed
#                 rhythm, and may still use every core
#   svc_cpuset    no period and no throttling: the service is never stopped, it just only ever
#                 runs on the cores it was given
# Raising a quota does nothing for a cpuset, and widening a cpuset does nothing for a quota.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS A1): KERNEL names the mechanism (all
# threads of one container on one CPU, waiting for the CPU behind their own siblings, other
# CPUs idle); spans and the latency histogram see "this service is slow"; logs see nothing.
#
# RESTORE: `docker update --cpuset-cpus ""` is treated as "no change", like the other docker
# update traps in faults/README.md. Cleanup therefore writes the FULL range (0..nproc-1) and
# checks the container's own cpuset.cpus.effective.
#
# Usage:
#   TARGET_SVC=carts ./svc_cpuset.sh inject [subtle|aggressive]
#   TARGET_SVC=carts ./svc_cpuset.sh cleanup | status
#   env: CPUSET   explicit core list for inject (default: the LAST core, or the last two)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="svc_cpuset_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="widen the cpuset back to all cores (docker update --cpuset-cpus 0-N)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
NCPU="$(nproc)"
FULL="0-$((NCPU - 1))"
effective() { docker exec "$CONTAINER" cat /sys/fs/cgroup/cpuset.cpus.effective 2>/dev/null | tr -d '\n'; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      # The LAST cores, not core 0: core 0 also takes most interrupts on these VMs, and the
      # point is a service short of cores, not a service sharing a core with the network stack.
      subtle)     CPUSET="${CPUSET:-$((NCPU - 2))-$((NCPU - 1))}" ;;
      aggressive) CPUSET="${CPUSET:-$((NCPU - 1))}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    BEFORE="$(effective)"
    # gt_begin FIRST: it stamps the start of the incident window, so anything done before it
    # is counted as baseline.
    gt_begin "$INTENSITY" "{\"cpuset\": \"$CPUSET\", \"cores_allowed_before\": \"$BEFORE\", \"host_cores\": $NCPU, \"container\": \"$CONTAINER\"}"
    docker update --cpuset-cpus="$CPUSET" "$CONTAINER" > /dev/null
    NOW="$(effective)"
    echo "[$FAULT_NAME] cpuset $BEFORE -> $NOW"
    [[ "$NOW" == "$CPUSET" ]] || echo "[$FAULT_NAME] WARN: asked for $CPUSET, the kernel reports $NOW"
    ;;
  cleanup)
    docker update --cpuset-cpus="$FULL" "$CONTAINER" > /dev/null
    NOW="$(effective)"
    [[ "$NOW" == "$FULL" ]] || echo "[$FAULT_NAME] WARN: restore asked for $FULL, the kernel reports $NOW"
    gt_end
    ;;
  status)
    echo "$CONTAINER cpuset.cpus.effective=$(effective) (host has $NCPU cores)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
