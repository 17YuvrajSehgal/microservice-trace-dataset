#!/bin/bash
# Fault recipe: an I/O limit on one container (cgroup v2 io.max on a database).
#
# The container may write only WBPS bytes per second (and WIOPS operations per second) to the
# disk. The disk itself is idle and fast; the kernel makes this one container wait. A database
# that syncs its journal on every write then answers slowly, and nothing on the host looks busy.
# This is what a small "provisioned IOPS" setting or a noisy-neighbour guard does in production.
#
# WHY THIS FAMILY. anomaly_disk makes the DEVICE busy: every container that touches the disk
# waits and iostat shows it. Here the device is not busy; one container waits on a limit. Same
# symptom for the service (slow writes), opposite picture on the host.
#
# Restart-free: the limit is one line in the container's io.max file, written on the host.
# Cleanup writes "max" back and reads the file.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS C4): the KERNEL shows the database's
# threads sleeping in write/fsync with the device idle; METRICS show the caller's answer time
# up; what users see is measured in the calibration, not assumed.
#
# Usage:
#   TARGET_SVC=carts-db ./io_cap.sh inject [subtle|aggressive] | cleanup | status
#   env: WBPS (bytes/s), WIOPS (operations/s)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

TARGET_SVC="${TARGET_SVC:-carts-db}"
FAULT_FAMILY="B_service_resource"
FAULT_NAME="io_cap_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"${TARGET_SVC%-db}\", \"front-end\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove the I/O limit (write 'MAJ:MIN wbps=max wiops=max' to the container's io.max)"

CONTAINER="$(resolve_container "$TARGET_SVC")"
CG="/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "$CONTAINER" 2>/dev/null).scope"
# The whole disk that holds Docker's data (limits go on the disk, not on a partition).
PART="$(df --output=source /var/lib/docker | tail -1)"
DISK="/dev/$(lsblk -no PKNAME "$PART" | head -1)"
DEV="$(lsblk -dno MAJ:MIN "$DISK" | tr -d ' ')"
iomax() { grep "^$DEV " "$CG/io.max" 2>/dev/null | tr -d '\n' || true; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) WBPS="${WBPS:-65536}";  WIOPS="${WIOPS:-20}" ;;
      subtle)     WBPS="${WBPS:-524288}"; WIOPS="${WIOPS:-100}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    [[ -f "$CG/io.max" && -n "$DEV" ]] || { echo "[$FAULT_NAME] no io.max at $CG or no device for $PART"; exit 1; }
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"wbps\": $WBPS, \"wiops\": $WIOPS, \"device\": \"$DEV\", \"disk\": \"$DISK\", \"container\": \"$CONTAINER\"}"
    echo "$DEV wbps=$WBPS wiops=$WIOPS" | sudo tee "$CG/io.max" > /dev/null
    echo "[$FAULT_NAME] io.max now: $(iomax)"
    ;;
  cleanup)
    echo "$DEV wbps=max wiops=max" | sudo tee "$CG/io.max" > /dev/null
    NOW="$(iomax)"
    [[ -z "$NOW" ]] || echo "[$FAULT_NAME] WARN: the limit was not removed, io.max has '$NOW'"
    echo "[$FAULT_NAME] io.max restored (line for $DEV now: '${NOW:-none}')"
    gt_end
    ;;
  status)
    echo "$CONTAINER io.max: '$(iomax)' (empty = no limit)"
    ;;
  *)
    echo "usage: TARGET_SVC=<svc> $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
