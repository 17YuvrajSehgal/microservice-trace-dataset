#!/bin/bash
# Fault recipe: a real-time thread that never sleeps, pinned to one core (host).
#
# One process with the SCHED_FIFO policy spins on one CPU. A real-time thread always runs before
# normal threads, so on that CPU normal threads get only what the kernel's real-time throttling
# leaves them (sched_rt_runtime_us: 95% to real-time by default, 5% to the rest). Threads that
# were running there must wait or move to another CPU.
#
# WHY THIS FAMILY. The CPU limits already collected act on one container (quota, cpuset,
# weight). This acts on one CPU, for everyone, through the scheduling POLICY - the shape of a
# misconfigured real-time task or a driver thread gone wrong.
#
# A helper process on the host, not inside a service (rule 2 of the candidate list): there is
# no service here that runs real-time threads. Its name is "python3" in the host's namespaces.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS A8): the KERNEL shows one CPU running one
# SCHED_FIFO task about 95% of the time, normal threads on that CPU waiting or migrating away;
# METRICS show the host one core busier and, at most, a small rise in answer times; logs and
# spans show nothing. What users see is measured in the calibration, not assumed.
#
# Usage:
#   ./rt_hog.sh inject [subtle|aggressive] | cleanup | status
#   env: RT_CPU (default: the last CPU), RT_PRIO (default 50)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="E_infrastructure"
FAULT_NAME="rt_hog"
FAULT_SCOPE="host"
TARGET_SERVICE="host"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"host\", \"threads that run on that CPU\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-blind_spot}"
REMEDIATION="stop the real-time task, or give it the normal policy (chrt -o -p 0 <pid>)"

PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
running() { [[ -f "$PIDFILE" ]] && sudo kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    NCPU="$(nproc)"
    RT_CPU="${RT_CPU:-$((NCPU - 1))}"; RT_PRIO="${RT_PRIO:-50}"
    case "$INTENSITY" in
      aggressive) HOGS="${HOGS:-1}" ;;
      subtle)     HOGS="${HOGS:-1}"; DUTY="${DUTY:-0.5}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    DUTY="${DUTY:-1.0}"
    mkdir -p "$FAULT_STATE_DIR"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"cpu\": $RT_CPU, \"policy\": \"SCHED_FIFO\", \"priority\": $RT_PRIO, \"duty\": $DUTY, \"rt_runtime_us\": $(cat /proc/sys/kernel/sched_rt_runtime_us)}"
    # duty < 1: spin for duty x 100 ms, sleep for the rest
    sudo nohup chrt -f "$RT_PRIO" taskset -c "$RT_CPU" python3 -c "
import time
d = $DUTY
while True:
    t = time.time() + 0.1 * d
    while time.time() < t:
        pass
    if d < 1.0:
        time.sleep(0.1 * (1 - d))" strata_rt_hog > /dev/null 2>&1 < /dev/null &
    sleep 1
    P="$(pgrep -n -f '^python3 .*strata_rt_hog' || true)"
    echo "$P" > "$PIDFILE"
    running || { echo "[$FAULT_NAME] the real-time process did not start"; exit 1; }
    echo "[$FAULT_NAME] pid $P on CPU $RT_CPU: $(chrt -p "$P" | tail -1), duty $DUTY"
    ;;
  cleanup)
    sudo pkill -f strata_rt_hog 2>/dev/null || true
    sleep 1
    if running || pgrep -f '^python3 .*strata_rt_hog' >/dev/null; then sudo pkill -9 -f strata_rt_hog 2>/dev/null || true; fi
    echo "[$FAULT_NAME] real-time process stopped (running now: $(running && echo yes || echo no))"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "real-time hog running: $(running && echo "yes, pid $(cat "$PIDFILE")" || echo no)"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
