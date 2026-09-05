#!/bin/bash
# Fault recipe: mining-shaped resource abuse (co-located workload container).
#
# A BENIGN SIMULATION on our own isolated VM: a SHA-256 loop plus a short TCP connection to a
# listener inside the same container, every few seconds. No mining, no pool, no external
# contact, no payload. What it reproduces is the SHAPE that abusive compute has in a kernel
# trace.
#
# WHY IT IS NOT JUST ANOTHER noisy_neighbor. That recipe runs stress-ng and is pure CPU burn.
# This has the same CPU profile plus one thing: a REGULAR, SMALL, OUTBOUND connection at a
# fixed interval - the stratum-style heartbeat that separates coordinated abuse from a
# badly-behaved batch job.
#
# So the pair asks a question we have never asked: given two workloads that both saturate CPU,
# can a blueprint tell "someone is using our machine" from "our own job is heavy"? Either it
# finds the beacon, which is a new discriminator, or it cannot, which is an honest limit.
# Naser said a negative result is a good result, and this is a clean way to get one.
#
# Naser, 2 Sept: "Mainly performance, but security can be a part of it as well."
#
# Pre-registered expectations: KERNEL only. No spans, no service logs, no service metrics.
#
# Usage:
#   ./resource_abuse.sh inject [subtle|aggressive]
#   ./resource_abuse.sh cleanup | status
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="H_security"
FAULT_NAME="resource_abuse"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"all services (mild)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="identify and remove the unauthorised workload; audit how it was scheduled"

CONTAINER="resource-abuse"

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      # subtle keeps CPU below the noisy_neighbor level on purpose, so the two are separated
      # by the beacon rather than by magnitude - which is the discriminator we want to test
      subtle)     THREADS="${THREADS:-2}" BEACON="${BEACON:-15}" CPUS="${CPUS:-1.0}" ;;
      aggressive) THREADS="${THREADS:-4}" BEACON="${BEACON:-5}"  CPUS="${CPUS:-2.0}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    workload_start "$CONTAINER" resource_abuse.py "$CPUS" -- "$THREADS" "$BEACON"
    gt_begin "$INTENSITY" "{\"hash_threads\": $THREADS, \"beacon_interval_s\": $BEACON, \"cpus_cap\": $CPUS, \"container\": \"$CONTAINER\", \"note\": \"benign simulation; beacon target is a local listener, nothing leaves the host\"}"
    ;;
  cleanup)  workload_stop "$CONTAINER"; gt_end ;;
  status)   workload_status "$CONTAINER" ;;
  *) echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
