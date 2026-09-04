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

# App profile: which containers to snapshot (docker-top for kernel-thread attribution) + dump
# logs for, and the LTTng session-name prefix. Defaults keep the frozen Sock Shop v1 behavior
# byte-identical; export these to collect from another stack. Train Ticket, e.g.:
#   TRACE_APP=trainticket \
#   CONTAINER_REGEX='trainticket_.*_1|^mysql$|^nacos$' \
#   LOG_CONTAINER_REGEX='trainticket_.*_1|^mysql$|^nacos$|^otel-collector$'
TRACE_APP="${TRACE_APP:-sockshop}"
CONTAINER_REGEX="${CONTAINER_REGEX:-docker-compose_(front-end|edge-router|carts|orders|payment|shipping|user|catalogue|catalogue-db|carts-db|orders-db|user-db|session-db|queue-master|rabbitmq)_1}"
LOG_CONTAINER_REGEX="${LOG_CONTAINER_REGEX:-docker-compose_(front-end|edge-router|carts|orders|payment|shipping|user|catalogue|catalogue-db|carts-db|orders-db|user-db|session-db|queue-master|rabbitmq|otel-collector)_1}"

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

    mapfile -t APP_CONTAINERS < <(
        docker ps --format '{{.Names}}' | grep -E "$CONTAINER_REGEX" || true
    )

    printf "%s\n" "${APP_CONTAINERS[@]}" \
        > "$META_DIR/container_list_${tag}.txt"

    for c in "${APP_CONTAINERS[@]}"; do
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
                # the namespace INODES. These are what the new kernel-event contexts carry,
                # so this file is the lookup table that turns an event into a container name.
                ls -l "/proc/$pid/ns" 2>/dev/null || true
            } > "$META_DIR/proc_${safe_name}_${tag}.txt"

            # CGROUP COUNTERS (v2). The kernel keeps per-cgroup counters that say directly
            # what a blueprint currently has to infer:
            #   cpu.stat       nr_throttled / throttled_usec  -> WHICH service is CPU-capped
            #   memory.events  low/high/max/oom               -> WHICH service hit its memory
            #                                                    limit, and whether it was
            #                                                    throttled or killed
            #   memory.stat    pgscan / pgsteal               -> reclaim, per cgroup
            #   io.stat        per-device bytes and ios       -> disk work, per container
            # Free to read, no tracing overhead, and they give per-run ground truth that does
            # not depend on our own analysis being right.
            cg="$(sed -n 's/^0:://p' "/proc/$pid/cgroup" 2>/dev/null | head -1)"
            if [[ -n "$cg" && -d "/sys/fs/cgroup$cg" ]]; then
                {
                    echo "container=$c"
                    echo "cgroup=$cg"
                    for f in cpu.stat cpu.max memory.events memory.max memory.current \
                             memory.stat io.stat pids.current; do
                        if [[ -r "/sys/fs/cgroup$cg/$f" ]]; then
                            echo "--- $f"
                            cat "/sys/fs/cgroup$cg/$f" 2>/dev/null || true
                        fi
                    done
                } > "$META_DIR/cgroup_${safe_name}_${tag}.txt"
            fi
        fi
    done
}

# Logs modality: one post-run dump per container (docker's json-file driver
# buffers the full run, so dumping after the run is lossless and adds no load
# inside the measured window). --since bounds the dump to this run; stdout and
# stderr are kept in one stream in emission order.
collect_logs() {
    mapfile -t LOG_CONTAINERS < <(
        docker ps --format '{{.Names}}' | grep -E "$LOG_CONTAINER_REGEX" || true
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

lttng create "${TRACE_APP}-ust" --output="$OUTPUT_DIR/ust"
lttng enable-event --python otel.spans
lttng add-context --userspace --type=vpid --type=vtid --type=procname 2>/dev/null || true
lttng start

sudo lttng create "${TRACE_APP}-kernel" --output="$OUTPUT_DIR/kernel"
# Large per-CPU ring buffers to avoid discarded events under peak stress.
# The LTTng kernel default (~1 MB/CPU) overflows during heavy bursts. We use
# many sub-buffers (8 MB x 32 = 256 MB/CPU) so that, while the consumer is
# starved of CPU/disk under load, there is almost always a free sub-buffer to
# rotate into instead of dropping events. Override via the env vars below if
# RAM is constrained (256 MB/CPU x N_CPU is reserved at session start).
sudo lttng enable-channel -k channel0 \
    --subbuf-size="${KERNEL_SUBBUF_SIZE:-8M}" \
    --num-subbuf="${KERNEL_NUM_SUBBUF:-32}"

# Kernel event selection: a CURATED profile (advisor-recommended) is used for
# EVERY run - all syscalls (covers filesystem read/write/open, process
# fork/exec/exit, and network socket/send/recv at the syscall boundary) plus
# the sched, block-I/O, network-device, and IRQ tracepoint families. MEMORY
# events (kmem_*, mm_*, page-fault/reclaim) are deliberately EXCLUDED - they
# are the highest-volume, most expensive class and are not needed by the L1/L2
# analysis (which reads syscalls + sched for wait attribution). This keeps
# kernel output ~2-3 GB/run vs ~8 GB for --all, which is what makes the ~40-run
# campaign fit on disk. KERNEL_EVENTS=all is an optional escape hatch (e.g. to
# re-add memory instrumentation for a one-off experiment); the campaign does
# NOT use it - the profile is the same for every run.
if [ "${KERNEL_EVENTS:-curated}" = "all" ]; then
    sudo lttng enable-event -k --all '*' --channel channel0
else
    # All syscalls (entry+exit), the core signal for L2 wait attribution.
    sudo lttng enable-event -k --syscall --all --channel channel0 2>/dev/null || true
    # Tracepoint families; some wildcards may match nothing on a given kernel,
    # so each is best-effort (|| true) and failures are non-fatal.
    # power_* ADDED FOR v2. `power_cpu_frequency` and `power_cpu_idle` were confirmed
    # available on the collection VM (lttng list --kernel, 2026-09-04). v1 never enabled them,
    # which is the ONLY reason "slow CPU clock / frequency scaling" sits in LATENCY-CAUSES.md
    # as never tried - not because it is invisible, but because we were not recording it.
    # Both are low volume: they fire on frequency and idle-state transitions, not per event.
    KERNEL_GROUPS='sched_* block_* net_* netif_* napi_* skb_* sock_* tcp_* udp_* irq_* softirq_* power_*'
    # Memory-management tracepoints are EXCLUDED from the default curated profile
    # (advisor guidance + storage: ~2-3 GB/run). Opt in with KERNEL_MEM=1 for the
    # memory-layer faults (host_mem, svc_mem_cap) so the kernel modality can see
    # reclaim / paging / page-cache writeback - the F3/F8 signature the study needs.
    # MEMORY TRACEPOINTS (v2 default ON, see KERNEL_MEM below).
    #
    # v1 left these off because they are the highest-volume class, and paid for it: our three
    # remaining wrong answers are all memory faults called noisy neighbours, and BOTH indirect
    # routes we tried died the same way - block-layer latency (F18) and device interrupt time
    # (F20) each separated the two on one application and failed on the other.
    #
    # But "memory tracepoints" is not one thing. The firehose is kmem_* and the page
    # alloc/free path; the signal we actually need - is this cgroup reclaiming? - lives in
    # vmscan_*, which is far cheaper. So KERNEL_MEM=1 now enables the TARGETED set, and
    # KERNEL_MEM=full adds the firehose for anyone who needs allocation detail.
    if [ "${KERNEL_MEM:-0}" = "full" ]; then
        KERNEL_GROUPS="$KERNEL_GROUPS kmem_* mm_* vmscan_* writeback_* compaction_* migrate_*"
        echo "[collect] KERNEL_MEM=full -> ALL memory tracepoints (very large traces)"
    elif [ "${KERNEL_MEM:-0}" = "1" ]; then
        KERNEL_GROUPS="$KERNEL_GROUPS vmscan_* writeback_* compaction_* migrate_*"
        echo "[collect] KERNEL_MEM=1 -> memory-management tracepoints ADDED to profile"
    fi
    for grp in $KERNEL_GROUPS; do
        sudo lttng enable-event -k "$grp" --channel channel0 2>/dev/null || true
    done
fi
sudo lttng add-context --kernel --channel channel0 --type=pid --type=tid --type=procname 2>/dev/null || true

# CONTAINER ATTRIBUTION (v2). procname is NOT enough: Sock Shop runs several Go services whose
# comm is all `app`, so three blueprints can say a fault is happening but not WHICH service -
# service-cpu-throttle, network-path-degradation and the disk/memory pair all end with
# "naming it needs cgroup-aware attribution we do not have from the trace".
#
# A namespace id on every event closes that gap. snapshot_metadata already records
# `ls -l /proc/<pid>/ns` per container, so the lookup table was always being collected - the
# key on the event was the missing half. Added one type at a time and best-effort, so a kernel
# missing one context does not cost us the others.
for ctx in cgroup_ns pid_ns net_ns mnt_ns ipc_ns user_ns; do
    if sudo lttng add-context --kernel --channel channel0 --type="$ctx" >/dev/null 2>&1; then
        echo "[$TYPE/$RUN] context ok: $ctx"
    else
        echo "[$TYPE/$RUN] context MISSING on this kernel: $ctx"
    fi
done

# Record exactly which events and contexts were enabled. Nothing did this before, so finding
# out what a stored trace contains meant opening it.
sudo lttng list "${TRACE_APP}-kernel" > "$META_DIR/lttng_enabled_kernel.txt" 2>&1 || true
lttng list "${TRACE_APP}-ust" > "$META_DIR/lttng_enabled_ust.txt" 2>&1 || true

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

# EVENT LOSS (v2). `lttng stop` reports discarded events and lost packets, and we used to
# throw that away with `|| true`. It is the difference between a good run and a silently
# corrupted one: a run that dropped a third of its sched_switch events looks exactly like a
# clean one, and every ratio computed from it is wrong. Buffer pressure also rises with the
# memory tracepoints on - which is precisely the runs we most care about in v2.
{
    echo "== ust stop =="
    lttng stop 2>&1 || true
    echo "== kernel stop =="
    sudo lttng stop 2>&1 || true
} | tee "$META_DIR/lttng_stop.txt"

# machine-readable, so the campaign driver can flag a run without parsing prose
python3 "$SCRIPT_DIR/parse_event_loss.py" \
    "$META_DIR/lttng_stop.txt" "$META_DIR/event_loss.json" || true

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
