#!/bin/bash
# Fault recipe: file-descriptor exhaustion on a target service.
#
# The running service's RLIMIT_NOFILE is lowered to just above what it is already using, so its
# own normal traffic runs it out. `accept` and `socket` then return EMFILE while the process
# keeps running - which is what a descriptor leak actually looks like from the kernel's side.
#
# THIS RECIPE WAS WRONG TWICE. Both mistakes are worth keeping, because both were the kind that
# produce a run labelled as a fault that never happened.
#
# 1. AN EXTERNAL PROCESS EATING DESCRIPTORS CANNOT WORK.
#    The first version ran a loop inside the container taking descriptors until EMFILE.
#    RLIMIT_NOFILE is PER PROCESS. A helper exhausting its own descriptors tells the service
#    nothing - the service keeps its own budget. The only shared ceiling is the system-wide
#    file-max, in the millions, and not reachable safely beside a live application. The smoke
#    test also caught that the target has no bash, so the `exec -a` the loop relied on did not
#    exist either: two independent reasons the same recipe could never have done its job.
#
# 2. APPLYING THE LIMIT BY RECREATING THE CONTAINER POLLUTES THE RUN.
#    The second version set `ulimits.nofile` in a compose override and recreated the service. It
#    worked - but it RESTARTS the service in the middle of a traced run. A restart is a huge
#    event in the kernel stream: process exit, process start, every descriptor closed and
#    reopened. The signature we would then be studying could be the restart rather than the
#    exhaustion, and no amount of downstream analysis could separate the two.
#
#    `prlimit` changes the limit on the LIVE process. No restart, nothing recreated, no compose
#    override, and the only thing added to the trace is the fault. It also restores exactly,
#    because the original value is read and saved before anything changes.
#
# MEASURED, NOT ASSUMED. The limit is set from what the service is using right now, so the
# recipe fits whatever it is pointed at. Sock Shop's Node front-end sits at 21 descriptors idle
# and climbs to ~151 under 150 concurrent requests; Train Ticket's front door is a Spring Cloud
# Gateway JVM and will sit far higher. A fixed number tuned on one of them would be either
# harmless or fatal on the other.
#
# PAIRS WITH dependency_outage. Both end with a service that stops serving. The difference is
# that this one is running and FAILING at a specific syscall, while an outage means it is not
# running at all. F11-F13 showed a paused container is invisible in the scheduler stream; this
# should be loud, because the kernel records EMFILE on every refused call.
#
# Pre-registered expectations: KERNEL (EMFILE returns, which we capture because every syscall
# is recorded with its return value) and LOGS (the service will complain).
#
# Usage:
#   ./fd_exhaustion.sh inject [subtle|aggressive]
#   ./fd_exhaustion.sh prove | cleanup | status
#     prove = drive load and report the peak descriptor count against the limit
#   env: TARGET_SVC   (default: the deployed app's front door - front-end on Sock Shop,
#                      ts-gateway-service on Train Ticket)
#        STRATA_APP   sockshop | trainticket
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

FAULT_FAMILY="G_resource_leak"
FAULT_NAME="fd_exhaustion"
FAULT_SCOPE="service"
# The front door of whichever application is deployed: it terminates every inbound connection,
# so it feels the limit first and its failure has a real blast radius. TT's analogue of
# front-end is ts-gateway-service (FAULTS-TT.md).
if [[ "${STRATA_APP:-sockshop}" == "trainticket" ]]; then
    TARGET_SVC="${TARGET_SVC:-ts-gateway-service}"
else
    TARGET_SVC="${TARGET_SVC:-front-end}"
fi
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$TARGET_SVC\", \"every caller of it\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="close descriptors on the error path; raise the limit only after fixing the leak"

STATE_DIR="${FAULT_STATE_DIR:-$HOME/fault-state}"
SAVED="$STATE_DIR/fd_exhaustion.original_limit"
mkdir -p "$STATE_DIR"

target_pid() {
    local c pid
    c="$(compose_container "$TARGET_SVC" 2>/dev/null || true)"
    [[ -z "$c" ]] && { echo "[$FAULT_NAME] cannot find a container for $TARGET_SVC" >&2; return 1; }
    pid="$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || true)"
    [[ -z "$pid" || "$pid" == "0" ]] && { echo "[$FAULT_NAME] $TARGET_SVC is not running" >&2; return 1; }
    echo "$pid"
}

limit_of() { sudo awk '/open files/{print $4}' "/proc/$1/limits" 2>/dev/null || echo 0; }
fds_of()   { sudo ls "/proc/$1/fd" 2>/dev/null | wc -l; }

# GENUINE idle use, not whatever the last thing to touch the service left behind.
#
# A single reading taken straight after a load probe returned 147 for a service that sits at 21:
# the probe's connections were still closing. The limit was then set to 155 and the fault barely
# bit - peak 148 against a ceiling of 155. Sockets in flight only ever ADD to the count, so the
# minimum across a few seconds is the honest floor.
idle_fds() {
    local pid="$1" n min=999999 i
    for i in 1 2 3 4 5 6; do
        n="$(fds_of "$pid" || true)"
        if [[ "$n" =~ ^[0-9]+$ ]] && [[ "$n" -lt "$min" ]]; then min="$n"; fi
        sleep 0.5
    done
    echo "$min"
}

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    # Headroom ABOVE current use, not an absolute number - see the header.
    case "$INTENSITY" in
      subtle)     HEADROOM="${HEADROOM:-64}" ;;
      aggressive) HEADROOM="${HEADROOM:-8}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac

    PID="$(target_pid)" || exit 1
    ORIG="$(limit_of "$PID")"
    if [[ ! "$ORIG" =~ ^[0-9]+$ ]] || [[ "$ORIG" -eq 0 ]]; then
        echo "[$FAULT_NAME] could not read the current limit for pid $PID - refusing to guess"
        exit 1
    fi
    # Saved BEFORE anything changes, so cleanup restores the real value rather than a default
    # that merely looked right on this VM. The pid goes with it - see cleanup.
    echo "$ORIG $PID" > "$SAVED"

    IDLE="$(idle_fds "$PID")"
    NOFILE="${NOFILE:-$(( IDLE + HEADROOM ))}"
    if [[ "$NOFILE" -ge "$ORIG" ]]; then
        echo "[$FAULT_NAME] computed limit $NOFILE is not below the current $ORIG - nothing to do"
        exit 1
    fi

    # The live process, no restart. Lowering the hard limit needs root, and cleanup raises it
    # again as root.
    if ! sudo prlimit --pid "$PID" --nofile="$NOFILE:$NOFILE"; then
        echo "[$FAULT_NAME] prlimit failed on pid $PID"
        exit 1
    fi
    NOW="$(limit_of "$PID")"
    if [[ "$NOW" != "$NOFILE" ]]; then
        echo "[$FAULT_NAME] the limit did not take: asked for $NOFILE, /proc reports $NOW"
        exit 1
    fi
    echo "[$FAULT_NAME] $TARGET_SVC (pid $PID) limit $ORIG -> $NOFILE, using $IDLE at idle"

    gt_begin "$INTENSITY" "{\"target_service\": \"$TARGET_SVC\", \"target_pid\": $PID, \"nofile_limit\": $NOFILE, \"nofile_original\": $ORIG, \"fds_idle\": $IDLE, \"headroom\": $HEADROOM, \"mechanism\": \"prlimit on the live process - RLIMIT_NOFILE lowered to just above measured idle use, so the service exhausts its own descriptors under normal load. No restart, so the trace contains the fault and nothing else.\"}"
    ;;

  prove)
    # Does the service ACTUALLY run out of descriptors, or is the cap just decoration?
    #
    # The first version of this check asked for failed requests and got errors=0, which looked
    # like a dead fault. It was not. Node does not refuse the connection - the kernel completes
    # the handshake into the listen backlog and the app accepts as descriptors free up. So the
    # requests get SLOW rather than failing, and a check keyed on errors would have thrown away
    # a working fault.
    #
    # What is true regardless of how the application reacts is that the descriptor count reaches
    # the ceiling. That is the fault itself, so that is what to measure.
    PID="$(target_pid)" || exit 1
    LIM="$(limit_of "$PID")"
    if [[ "${STRATA_APP:-sockshop}" == "trainticket" ]]; then
        URL="${PROBE_URL:-http://localhost:8080/index.html}"
    else
        URL="${PROBE_URL:-http://localhost:80/catalogue}"
    fi

    OUT="$(mktemp)"
    python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/code-defects/loadprobe.py" "$URL" "${PROBE_N:-600}" "${PROBE_CONC:-150}" >"$OUT" 2>&1 &
    probe=$!

    # `if`, not `&&`, and `|| true` on the sample. With `set -e` a false `[[ ]]` at the end of a
    # loop body kills the shell, and so does a command substitution whose pipeline fails once the
    # process has gone. Either would abort the probe and read as "the fault did nothing".
    peak=0
    while kill -0 "$probe" 2>/dev/null; do
        n="$(fds_of "$PID" || true)"
        if [[ "$n" =~ ^[0-9]+$ ]] && [[ "$n" -gt "$peak" ]]; then peak="$n"; fi
        sleep 0.2
    done
    wait "$probe" 2>/dev/null || true

    result="$(tr '\n' ' ' <"$OUT" 2>/dev/null || true)"; rm -f "$OUT"
    echo "peak fds $peak of limit $LIM | $result"
    # within 4 of the ceiling counts as reached - a 0.2 s sampler cannot catch every instant
    [[ "$LIM" -gt 0 && "$peak" -ge $(( LIM - 4 )) ]]
    ;;

  cleanup)
    # Restore whatever was saved at inject time. If the container has restarted since, its new
    # process already has the stock limit and there is nothing to undo - say so rather than
    # fail, because a cleanup that exits nonzero stops a campaign run.
    SURVIVED="unknown"
    if [[ -f "$SAVED" ]]; then
        read -r ORIG WAS_PID < "$SAVED"
        if PID="$(target_pid 2>/dev/null)"; then
            sudo prlimit --pid "$PID" --nofile="$ORIG:$ORIG" 2>/dev/null || true
            echo "[$FAULT_NAME] $TARGET_SVC (pid $PID) limit restored to $(limit_of "$PID")"
            # DID THE FAULT LAST THE WHOLE WINDOW?
            #
            # prlimit applies to ONE process. If the container restarted mid-run the new process
            # got the stock limit and the fault quietly ended partway through, while ground truth
            # would still claim a full injection window. That is a mislabelled run, so record the
            # answer instead of assuming it.
            # `if`, not `x && y`: with set -e a standalone AND-list whose test is false exits
            # the script, which here would abort cleanup exactly when nothing was wrong.
            if [[ "$PID" == "$WAS_PID" ]]; then
                SURVIVED="true"
            else
                SURVIVED="false"
                echo "[$FAULT_NAME] WARNING: pid changed $WAS_PID -> $PID; the service restarted and the fault ended early"
            fi
        else
            echo "[$FAULT_NAME] $TARGET_SVC not running at cleanup - nothing to restore"
            SURVIVED="false"
        fi
        rm -f "$SAVED"
    else
        echo "[$FAULT_NAME] no saved limit - nothing to restore"
    fi
    gt_end
    # Never let bookkeeping fail a cleanup: a nonzero exit here would stop a campaign run.
    GTF="$(gt_file)"
    if [[ -f "$GTF" ]]; then
        python3 -c 'import json,sys
p,v=sys.argv[1],sys.argv[2]
d=json.load(open(p))
d["fault"]["target_pid_survived_window"]={"true":True,"false":False}.get(v)
json.dump(d,open(p,"w"),indent=2)' "$GTF" "$SURVIVED" || true
    fi
    ;;

  status)
    if PID="$(target_pid 2>/dev/null)"; then
        echo "limit: $(limit_of "$PID")"
        echo "in use: $(fds_of "$PID")"
    else
        echo "$TARGET_SVC not running"
    fi
    ;;

  *) echo "usage: $0 inject [subtle|aggressive] | prove | cleanup | status"; exit 1 ;;
esac
