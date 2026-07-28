#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

TYPE=$1
RUN=$2
DURATION=${3:-120}
EXTRA_ARG=${4:-}
OUTPUT_DIR=~/traces/$TYPE/$RUN
META_DIR="$OUTPUT_DIR/meta"
LOGS_DIR="$OUTPUT_DIR/logs"
OTLP_DIR="$OUTPUT_DIR/otlp"

# Global OTLP span file written by the otel-collector service (bind mount
# ./otlp-out next to docker-compose.otel.yml). Per run we slice the byte range
# appended during this run; exact run-window filtering happens downstream via
# the per-span timestamps.
OTLP_SRC="${OTLP_SRC:-$SCRIPT_DIR/otlp-out/spans.jsonl}"
# Seconds to wait after the run before slicing, so the collector's batch
# processor flushes trailing spans to disk.
OTLP_DRAIN_S="${OTLP_DRAIN_S:-3}"

mkdir -p "$OUTPUT_DIR"/{kernel,ust}
mkdir -p "$META_DIR" "$LOGS_DIR" "$OTLP_DIR"

# Recorded before tracing starts; used as the --since bound for the post-run
# `docker logs` dump (a slightly early bound only means a superset of lines).
RUN_START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)

snapshot_metadata() {
    local tag="$1"

    {
        echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "hostname=$(hostname)"
        echo "kernel=$(uname -r)"
        echo "type=$TYPE"
        echo "run=$RUN"
        echo "duration=$DURATION"
        # Cross-modality clock anchor: LTTng stamps events with
        # CLOCK_MONOTONIC, while docker logs / OTLP spans / Prometheus use
        # CLOCK_REALTIME. A (realtime, monotonic) pair read back-to-back at
        # start, every tick, and end lets downstream compute the offset and
        # bound its drift over the run. BOOTTIME is a suspend-aware
        # cross-check.
        python3 - <<'PY' 2>/dev/null || echo "clock_read=failed"
import time
print(f"clock_realtime_ns={time.clock_gettime_ns(time.CLOCK_REALTIME)}")
print(f"clock_monotonic_ns={time.clock_gettime_ns(time.CLOCK_MONOTONIC)}")
print(f"clock_boottime_ns={time.clock_gettime_ns(time.CLOCK_BOOTTIME)}")
PY
        # NTP sync quality (chrony on GCP images; timesyncd fallback).
        chronyc tracking 2>/dev/null | sed 's/^/ntp_/' \
            || timedatectl show-timesync 2>/dev/null | sed 's/^/ntp_/' \
            || echo "ntp_status=unavailable"
    } > "$META_DIR/runinfo_${tag}.txt"

    docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' \
        > "$META_DIR/docker_ps_${tag}.txt" 2>&1 || true

    ps -eLo pid,tid,ppid,psr,cls,pri,stat,comm,cmd \
        > "$META_DIR/ps_threads_${tag}.txt" 2>&1 || true

    mapfile -t SOCKSHOP_CONTAINERS < <(
        docker ps --format '{{.Names}}' | grep -E 'docker-compose_(front-end|edge-router|carts|orders|payment|shipping|user|catalogue|catalogue-db|carts-db|orders-db|user-db|session-db|queue-master|rabbitmq)_1' || true
    )

    printf "%s\n" "${SOCKSHOP_CONTAINERS[@]}" \
        > "$META_DIR/container_list_${tag}.txt"

    for c in "${SOCKSHOP_CONTAINERS[@]}"; do
        safe_name="${c//\//_}"

        docker inspect "$c" > "$META_DIR/inspect_${safe_name}_${tag}.json" 2>&1 || true
        docker top "$c" -eo pid,tid,ppid,psr,stat,comm,args > "$META_DIR/top_${safe_name}_${tag}.txt" 2>&1 || true

        pid="$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || echo '')"
        if [[ -n "$pid" && "$pid" != "0" ]]; then
            {
                echo "container=$c"
                echo "host_pid=$pid"
                echo
                cat "/proc/$pid/cgroup" 2>/dev/null || true
                echo
                ls -l "/proc/$pid/ns" 2>/dev/null || true
            } > "$META_DIR/proc_${safe_name}_${tag}.txt"
        fi
    done
}

# Logs modality: one post-run dump per container (docker's json-file driver
# buffers the full run, so dumping after the run is lossless and adds no load
# inside the measured window). --since bounds the dump to this run; stdout and
# stderr are kept in one stream in emission order.
collect_logs() {
    mapfile -t LOG_CONTAINERS < <(
        docker ps --format '{{.Names}}' | grep -E 'docker-compose_(front-end|edge-router|carts|orders|payment|shipping|user|catalogue|catalogue-db|carts-db|orders-db|user-db|session-db|queue-master|rabbitmq|otel-collector)_1' || true
    )

    for c in "${LOG_CONTAINERS[@]}"; do
        safe_name="${c//\//_}"
        docker logs --timestamps --since "$RUN_START_UTC" "$c" \
            > "$LOGS_DIR/${safe_name}.log" 2>&1 || true
    done

    echo "[$TYPE/$RUN] logs: dumped ${#LOG_CONTAINERS[@]} containers since $RUN_START_UTC"
}

# OTLP slice bookkeeping: byte size of the global span file at run start.
otlp_start_offset() {
    if [[ -f "$OTLP_SRC" ]]; then
        stat -c %s "$OTLP_SRC"
    else
        echo 0
    fi
}

# Pre-flight: clear any LTTng state left by a previous run that was
# interrupted before its teardown (e.g. an SSH drop mid-collection). A leaked
# session leaves the consumer daemon wedged, and a plain `lttng destroy` then
# BLOCKS FOREVER waiting for it to flush - which is how the whole rig hangs.
# So bound every destroy with `timeout`, and if it does not return, force-kill
# the daemons (SIGKILL, no destroy) and let the create below respawn them.
lttng_preflight() {
    if ! timeout 10 lttng destroy -a >/dev/null 2>&1; then
        echo "[preflight] user lttng destroy wedged; force-killing daemons"
        pkill -9 -x lttng 2>/dev/null || true
        pkill -9 lttng-sessiond lttng-consumerd 2>/dev/null || true
    fi
    if ! sudo timeout 10 lttng destroy -a >/dev/null 2>&1; then
        echo "[preflight] root lttng destroy wedged; force-killing daemons"
        sudo pkill -9 lttng-sessiond lttng-consumerd lttng-runas 2>/dev/null || true
    fi
    sleep 1
}
lttng_preflight

lttng create sockshop-ust --output="$OUTPUT_DIR/ust"
lttng enable-event --python otel.spans
lttng add-context --userspace --type=vpid --type=vtid --type=procname 2>/dev/null || true
lttng start

sudo lttng create sockshop-kernel --output="$OUTPUT_DIR/kernel"
# Large per-CPU ring buffers to avoid discarded events under peak stress.
# The LTTng kernel default (~1 MB/CPU) overflows during heavy bursts. We use
# many sub-buffers (8 MB x 32 = 256 MB/CPU) so that, while the consumer is
# starved of CPU/disk under load, there is almost always a free sub-buffer to
# rotate into instead of dropping events. Override via the env vars below if
# RAM is constrained (256 MB/CPU x N_CPU is reserved at session start).
sudo lttng enable-channel -k channel0 \
    --subbuf-size="${KERNEL_SUBBUF_SIZE:-8M}" \
    --num-subbuf="${KERNEL_NUM_SUBBUF:-32}"
sudo lttng enable-event -k --all '*' --channel channel0
sudo lttng add-context --kernel --channel channel0 --type=pid --type=tid --type=procname 2>/dev/null || true
sudo lttng start

OTLP_START_OFFSET=$(otlp_start_offset)

snapshot_metadata "start"

(
    while true; do
        sleep 10
        snapshot_metadata "tick_$(date -u +%Y%m%dT%H%M%SZ)"
    done
) &
SNAP_PID=$!

python3 "$SCRIPT_DIR/agents/otel-to-lttng.py" ${EXTRA_ARG:+$EXTRA_ARG} &
RELAY_PID=$!

echo "[$TYPE/$RUN] FULL TRACING (Kernel+UST) for ${DURATION}s..."
sleep "$DURATION"

kill "$SNAP_PID" 2>/dev/null || true
wait "$SNAP_PID" 2>/dev/null || true

kill "$RELAY_PID" 2>/dev/null || true
wait "$RELAY_PID" 2>/dev/null || true

snapshot_metadata "end"

lttng stop || true
sudo lttng stop || true
lttng destroy || true
sudo lttng destroy || true

# --- Post-run harvest (after LTTng teardown so it cannot perturb tracing) ---

collect_logs

if [[ -f "$OTLP_SRC" ]]; then
    sleep "$OTLP_DRAIN_S"
    OTLP_END_OFFSET=$(otlp_start_offset)
    if [[ "$OTLP_END_OFFSET" -gt "$OTLP_START_OFFSET" ]]; then
        tail -c +"$((OTLP_START_OFFSET + 1))" "$OTLP_SRC" > "$OTLP_DIR/spans.jsonl"
    else
        : > "$OTLP_DIR/spans.jsonl"
    fi
    {
        echo "otlp_src=$OTLP_SRC"
        echo "start_offset=$OTLP_START_OFFSET"
        echo "end_offset=$OTLP_END_OFFSET"
        echo "lines=$(wc -l < "$OTLP_DIR/spans.jsonl")"
        echo "drain_seconds=$OTLP_DRAIN_S"
    } > "$OTLP_DIR/slice_info.txt"
    echo "[$TYPE/$RUN] otlp: sliced $((OTLP_END_OFFSET - OTLP_START_OFFSET)) bytes ($(wc -l < "$OTLP_DIR/spans.jsonl") lines)"
    # Rotate the global collector span file so it cannot grow unbounded across
    # a campaign. The collector appends with O_APPEND, so truncating to 0 is
    # safe (its next write lands at offset 0, and the next run captures a fresh
    # start offset). Root-owned (collector runs as uid 0), hence sudo.
    sudo truncate -s 0 "$OTLP_SRC" 2>/dev/null || true
else
    echo "[$TYPE/$RUN] otlp: $OTLP_SRC not found (collector not deployed?) - skipping"
fi

echo "$TYPE,$RUN,$(date -u +%Y-%m-%dT%H:%M:%SZ),${DURATION}s,FULL" >> "$META_DIR/trace_runs.csv"

# The kernel session runs as root, so its CTF output is root-owned. Hand the
# whole bundle back to the invoking user so downstream tools (audit,
# babeltrace2, the loader SDK) and dataset consumers can read it without sudo.
sudo chown -R "$(id -u):$(id -g)" "$OUTPUT_DIR" 2>/dev/null || true

echo "[$TYPE/$RUN] DONE. $(du -sh "$OUTPUT_DIR")"
