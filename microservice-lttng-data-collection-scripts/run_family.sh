#!/bin/bash
# v3 collection driver: ONE fault family, one run at a time.
#
#   ./run_family.sh <recipe> [intensity] [repeats] [workload]
#       e.g.  ./run_family.sh code_lock_contended aggressive 5 steady
#
# The v2 driver (run_campaign.sh) loops over the whole matrix. v3 collects one family, checks
# it, and only then moves on, so this driver takes the family on the command line. Per run it
# does exactly what run_campaign.sh does: run_scenario.sh, then campaign_finish_run.sh
# (package, event loss, move to the archive dir), then one manifest line.
#
# Differences from v2, all recorded in each bundle's meta/load_setup.txt:
#   LOAD_SETTLE_S=30   the load runs 30 s before tracing opens, so the baseline is at steady
#                      load (v2 baselines contain the ramp-up, CAMPAIGN-ISSUES 20)
#   ARCHIVE_DIR        ~/archive/runs on the boot disk (no separate archive disk in v3)
#   EXTRA_LOAD_CMD     passed through if the family sets it below
#   WARMUP_S           seconds of normal load before the first run (use after a VM start)
#
# Resumable: a run whose bundle already has meta/runinfo_end.txt is skipped.
# Long unattended run:  nohup ./run_family.sh code_lock_contended aggressive 5 > ~/family.out 2>&1 &
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RECIPE="${1:?usage: run_family.sh <recipe> [intensity] [repeats] [workload]}"
INTENSITY="${2:-aggressive}"
REPEATS="${3:-5}"
WORKLOAD="${4:-steady}"
export BASELINE_S="${BASELINE_S:-60}" INJECTION_S="${INJECTION_S:-120}" RECOVERY_S="${RECOVERY_S:-60}"
export LOAD_SETTLE_S="${LOAD_SETTLE_S:-30}"
export ARCHIVE_DIR="${ARCHIVE_DIR:-$HOME/archive/runs}"
USERS_STEADY="${USERS_STEADY:-150}"
USERS_BURST="${USERS_BURST:-300}"
MANIFEST="$HOME/campaign_manifest.csv"
mkdir -p "$ARCHIVE_DIR"
[[ ! -f "$MANIFEST" ]] && echo "run_id,recipe,intensity,workload,repeat,verification,event_loss,timestamp_utc" > "$MANIFEST"

# Per-family extra load. Kept here, next to the family name, so a run cannot be started
# without it by mistake.
case "$RECIPE" in
    code_lock_contended)
        # Two background conditions, the SAME in baseline, injection and recovery, so the only
        # thing that changes at injection is the lock. Calibrated on the VM, 24-11-2026, under
        # the normal 150-user load (progress-notes/24-11-2026/decisions.md):
        #
        #  1. a constant 5 ms delay on the catalogue's database (toxiproxy). Our local database
        #     answers in 0.4 ms, so a list request holds the lock for about 1 ms and never
        #     queues. With 5 ms it holds it for about 12 ms, like a database over a network.
        #  2. 4 clients that each ask the catalogue for the list every 100 ms (40 requests/s).
        #
        # With both: those clients see a median of 24 ms with the defect off and 80 ms with it
        # on, and the host is 41% busy either way. What did NOT work: 20 clients as fast as
        # they can (host 81% busy in the baseline, and the fault made the host LESS busy), and
        # the delay alone without extra clients (p95 34 -> 40 ms at 5 ms: too weak).
        LOCK_DB_DELAY_MS="${LOCK_DB_DELAY_MS:-5}"
        LOCK_CLIENTS="${LOCK_CLIENTS:-4}"
        LOCK_INTERVAL_MS="${LOCK_INTERVAL_MS:-100}"
        source "$SD/faults/fault_lib.sh"
        toxic_del catalogue-db bg_latency
        toxic_add catalogue-db "{\"name\":\"bg_latency\",\"type\":\"latency\",\"stream\":\"downstream\",\"attributes\":{\"latency\":$LOCK_DB_DELAY_MS,\"jitter\":0}}"             || { echo "FATAL: could not add the background database delay"; exit 1; }
        trap 'toxic_del catalogue-db bg_latency; echo "background database delay removed"' EXIT
        export RUN_NOTE="background: ${LOCK_DB_DELAY_MS} ms delay on catalogue-db (toxiproxy bg_latency) for the whole run; extra load ${LOCK_CLIENTS} clients every ${LOCK_INTERVAL_MS} ms on the catalogue list endpoint"
        # The address is resolved when the load starts, AFTER `arm` recreated the container.
        export EXTRA_LOAD_CMD="python3 $SD/faults/code-defects/loadprobe.py http://\$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \$(docker ps --format '{{.Names}}' | grep -m1 'catalogue_1'))/catalogue 1000000000 $LOCK_CLIENTS $LOCK_INTERVAL_MS"
        ;;
    syn_flood)
        # About 20,000 SYNs and as many SYN-ACKs per second, each seen on two interfaces as a
        # large net_dev_queue event (calibrated 28-11-2026). Same buffer size as slow_client.
        export KERNEL_NUM_SUBBUF="${KERNEL_NUM_SUBBUF:-96}"
        export RUN_NOTE="kernel ring buffers raised to ${KERNEL_NUM_SUBBUF} sub-buffers per CPU for this family (about 80,000 extra packet events per second)"
        ;;
    code_ctxswitch_storm)
        # The storm adds about 200,000 context switches per second (calibrated 27-11-2026), each
        # with its wake-up and sleep system call. Same buffer size as slow_client, for the same reason.
        export KERNEL_NUM_SUBBUF="${KERNEL_NUM_SUBBUF:-96}"
        export RUN_NOTE="kernel ring buffers raised to ${KERNEL_NUM_SUBBUF} sub-buffers per CPU for this family (the fault adds about 200,000 context switches per second)"
        ;;
    slow_client)
        # While the slow clients hold its threads the carts JVM polls its sockets in a tight
        # loop (measured 25-11-2026: 170,000 read and 340,000 futex calls per second), which
        # doubles the kernel event rate. With the default 32 sub-buffers per CPU the second
        # check run lost 1,096,369 events (the first lost none). Three times the buffer.
        export KERNEL_NUM_SUBBUF="${KERNEL_NUM_SUBBUF:-96}"
        export RUN_NOTE="kernel ring buffers raised to ${KERNEL_NUM_SUBBUF} sub-buffers per CPU for this family (the fault doubles the event rate)"
        ;;
    cpu_weight)
        # A CPU weight only matters on a busy host, so a neighbour keeps every core busy for the
        # WHOLE run (baseline, injection and recovery alike); the only thing that changes at
        # injection is the weight. Calibrated 25-11-2026: 12 busy processes at the default
        # weight take the host from 50% to 100% busy and already slow the baseline (cart rate
        # 120 -> 91/s, p95 23 -> 88 ms, front-end p95 50 -> 240 ms). That is the price of this
        # family; its baseline is NOT comparable with the other families' baselines.
        NEIGHBOUR_PROCS="${NEIGHBOUR_PROCS:-12}"
        docker rm -f cpu-neighbour >/dev/null 2>&1 || true
        docker run -d --name cpu-neighbour stratatrace-workload:v1 python3 -c "
import os
for i in range($NEIGHBOUR_PROCS - 1):
    if os.fork() == 0: break
while True: pass" >/dev/null || { echo "FATAL: could not start the busy neighbour"; exit 1; }
        trap 'docker rm -f cpu-neighbour >/dev/null 2>&1; echo "busy neighbour removed"' EXIT
        export RUN_NOTE="background: container cpu-neighbour with ${NEIGHBOUR_PROCS} busy processes at the default CPU weight for the whole run (host about 100% busy in the baseline too)"
        sleep 20
        ;;
esac

if [[ "$WORKLOAD" == "burst" ]]; then USERS="$USERS_BURST"; else USERS="$USERS_STEADY"; fi
echo "=== v3 family $RECIPE: $REPEATS runs, $INTENSITY/$WORKLOAD, users=$USERS, settle=${LOAD_SETTLE_S}s ==="
[[ -n "${EXTRA_LOAD_CMD:-}" ]] && echo "    extra load: $EXTRA_LOAD_CMD"
[[ -n "${RUN_NOTE:-}" ]] && echo "    $RUN_NOTE"

# WARMUP_S (default 0): drive the normal load this long before the first run. Needed after a
# VM start: measured 24-11-2026, the first minute of load on a freshly started VM had the host
# 81% busy and carts at 3.4 cores (the JVMs compiling), against 45% and 0.7 cores once warm.
if [[ "${WARMUP_S:-0}" -gt 0 ]]; then
    echo "warming up for ${WARMUP_S}s"
    python3 "$SD/load_generator.py" --host "${FRONTEND_HOST:-http://localhost:80}" --users "$USERS"         --duration "$WARMUP_S" --profile steady --think-min 0.1 --think-max 0.3         --output /tmp/warmup_load.csv > /tmp/warmup_load.log 2>&1 || true
    rm -f /tmp/warmup_load.csv
fi

for r in $(seq 1 "$REPEATS"); do
    RUN="${RECIPE}_${INTENSITY}_${WORKLOAD}_r${r}"
    RUN_DIR="$HOME/traces/${RECIPE}/${RUN}"
    ARCHIVED="$ARCHIVE_DIR/${RECIPE}/${RUN}"
    if [[ -f "$RUN_DIR/meta/runinfo_end.txt" || -f "$ARCHIVED/meta/runinfo_end.txt" ]]; then
        echo "[$r/$REPEATS] SKIP $RUN (already collected)"
        continue
    fi
    echo "[$r/$REPEATS] RUN  $RUN  $(date -u +%H:%M:%S)"
    PROFILE="$WORKLOAD" "$SD/run_scenario.sh" "$RECIPE" "$INTENSITY" "$RUN" "$USERS" \
        > "$HOME/${RUN}.log" 2>&1 || echo "[$r] WARN: run_scenario returned nonzero for $RUN"
    loss=$(bash "$SD/campaign_finish_run.sh" "$RUN_DIR" "$RUN" | tail -1)
    verdict="n/a"
    for d in "$RUN_DIR" "$ARCHIVED"; do
        if [[ -f "$d/verification.json" ]]; then
            verdict=$(python3 -c \
                "import json;print(json.load(open('$d/verification.json')).get('verification_status','n/a'))" 2>/dev/null || echo n/a)
            break
        fi
    done
    echo "${RUN},${RECIPE},${INTENSITY},${WORKLOAD},${r},${verdict},${loss},$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFEST"
    echo "[$r/$REPEATS] DONE $RUN -> verification=$verdict event_loss=$loss"

    # STOP AT THE FIRST BAD RUN. A family is collected unattended; if the quality gate says a
    # bundle is not usable, or the extra load never sent a request, the next four runs would
    # be bad in the same way. Stop, keep the evidence, and let a person look.
    bad=""
    for d in "$RUN_DIR" "$ARCHIVED"; do
        [[ -f "$d/run_quality.json" ]] || continue
        python3 -c "import json,sys; sys.exit(0 if json.load(open('$d/run_quality.json')).get('usable') else 1)"             || bad="run_quality.json says NOT USABLE"
        # disk_full has no metric signature (measured), so the proof that the fault happened
        # is the database's own log inside the bundle.
        if [[ "$RECIPE" == "disk_full" ]]; then
            nospace=$(cat "$d"/logs/*carts-db*.log 2>/dev/null | grep -c 'No space left on device')
            aborts=$(cat "$d"/logs/*carts-db*.log 2>/dev/null | grep -c 'aborting after')
            echo "[$r/$REPEATS] database log: $nospace lines 'No space left on device', $aborts aborts"
            [[ "$nospace" -gt 0 && "$aborts" -gt 0 ]] || bad="${bad:+$bad; }the database log shows no out-of-space abort"
        fi
        # port_scan has no metric signature either (measured): the proof is the scanner's count.
        if [[ "$RECIPE" == "unexpected_exec" ]]; then
            rounds=$(grep -a -o 'stopped after [0-9]* rounds' "$HOME/${RUN}.log" 2>/dev/null | grep -o '[0-9]*' | tail -1)
            echo "[$r/$REPEATS] shell rounds: ${rounds:-0}"
            [[ "${rounds:-0}" -ge 4 ]] || bad="${bad:+$bad; }the shell ran fewer than 4 rounds"
        fi
        if [[ "$RECIPE" == "port_scan" ]]; then
            tried=$(grep -a -o 'scanner stopped: stopped: sweeps [0-9]*, tried [0-9]*' "$HOME/${RUN}.log" 2>/dev/null | grep -o '[0-9]*$' | tail -1)
            echo "[$r/$REPEATS] scanner: ${tried:-0} connection attempts"
            [[ "${tried:-0}" -ge 10000 ]] || bad="${bad:+$bad; }the scanner reported fewer than 10000 attempts"
        fi
        if [[ -n "${EXTRA_LOAD_CMD:-}" ]]; then
            n=$(grep -o 'n=[0-9]*' "$d/meta/extra_load.log" 2>/dev/null | tail -1 | cut -d= -f2)
            [[ "${n:-0}" -gt 0 ]] || bad="${bad:+$bad; }the extra load reported no completed requests"
            echo "[$r/$REPEATS] extra load: $(tail -1 "$d/meta/extra_load.log" 2>/dev/null)"
        fi
        break
    done
    # A run that lost kernel events is not usable for a kernel blueprint, and the next runs of
    # the same family would lose them too (measured on slow_client, 25-11-2026: the fault
    # doubles the event rate and the second check run lost 1,096,369 events). Until that day
    # the driver went on after such a run.
    [[ "$loss" == "clean" ]] || bad="${bad:+$bad; }kernel events were lost ($loss)"
    if [[ -n "$bad" && "${STOP_ON_BAD:-1}" == "1" ]]; then
        echo "*** STOPPING family $RECIPE after $RUN: $bad"
        echo "*** Fix the cause and re-run; finished runs are skipped. STOP_ON_BAD=0 to continue anyway."
        exit 2
    fi
done
echo "=== family $RECIPE done; bundles in $ARCHIVE_DIR/$RECIPE ==="
