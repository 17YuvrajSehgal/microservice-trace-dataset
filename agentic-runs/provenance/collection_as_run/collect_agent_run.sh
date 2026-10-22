#!/bin/bash
# One agentic OS-noise run (runs ON the collection VM, as the signed-in user).
#
#   ./collect_agent_run.sh <run_name> <cpu.max> <task_script> [task_arg] [mem_limit]
#   e.g. ./collect_agent_run.sh t2_cap50_r1 "50000 100000" t2_medium.sh
#        ./collect_agent_run.sh t6_high1g_r1 max t6_memtouch.sh 1073741824 high:2G
#
# cpu.max values: "max" (uncapped), "100000 100000" (1 core),
#                 "50000 100000" (0.5), "25000 100000" (0.25).
# mem_limit (problem #3): "" (none), "high:<N>" -> memory.high (soft,
#                 recoverable), "max:<N>" -> memory.max (hard, OOM cliff).
#                 N accepts cgroup suffixes (2G, 900M) or bytes.
#
# Mirrors collect_trace.sh: curated v2 kernel profile, clock anchors,
# cpu.stat ground truth, enabled-events manifest. No UST session - the
# agent is not OTel-instrumented; kernel-only is the design (PLAN.md).
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
RUN=$1; CAP=$2; TASK=$3
TASK_ARG=${4:-}   # optional task variant (e.g. worker count W for t4_parallel)
MEM_LIMIT=${5:-}  # optional "high:<N>" or "max:<N>" for problem #3
IO_LIMIT=${6:-}   # optional "rbps:<N>" (bytes/s) for problem #4
BASE=${RUNS_DIR:-$HOME/runs}
OUT=$BASE/$RUN
CLAUDE=${CLAUDE_BIN:-$HOME/.local/bin/claude}
CG=/sys/fs/cgroup/agent

sudo rm -rf "$OUT"; mkdir -p "$OUT/meta"

# --- fresh task repo ---
rm -rf "$HOME/task"
TASK_ARG="$TASK_ARG" bash "$SCRIPT_DIR/tasks/$TASK" "$HOME/task"
PROMPT=$(cat "$HOME/task/.prompt")

# --- cgroup (root writes: cgroup-v2 delegation blocks non-root moves).
#     cpu.stat is cumulative and cannot be zeroed, so recreate the cgroup
#     each run - then cpu.stat.before is ~0 and .after is this run's usage. ---
sudo rmdir $CG 2>/dev/null || true
sudo mkdir -p $CG
echo "$CAP" | sudo tee $CG/cpu.max >/dev/null
cat $CG/cpu.stat > "$OUT/meta/cpu.stat.before"

# --- memory knob (problem #3): set memory.high or memory.max, snapshot the
#     memory counters before/after (the cpu.stat analog for reclaim/OOM). ---
if [ -n "$MEM_LIMIT" ]; then
    MEM_KNOB=${MEM_LIMIT%%:*}        # high | max
    MEM_VAL=${MEM_LIMIT#*:}
    echo "$MEM_VAL" | sudo tee "$CG/memory.$MEM_KNOB" >/dev/null
fi
cat $CG/memory.events > "$OUT/meta/memory.events.before" 2>/dev/null || true
cat $CG/memory.stat   > "$OUT/meta/memory.stat.before"   2>/dev/null || true

# --- io knob (problem #4): throttle the cgroup's disk bandwidth. Find the
#     backing block device for $HOME and set io.max rbps on it. ---
if [ -n "$IO_LIMIT" ]; then
    # the io controller must be delegated to child cgroups (cpu/memory/pids
    # are enabled by default on this VM, io is not). Idempotent; safe while
    # the agent cgroup is still empty.
    echo +io | sudo tee /sys/fs/cgroup/cgroup.subtree_control >/dev/null 2>&1 || true
    IO_RBPS=${IO_LIMIT#*:}
    SRC=$(df --output=source "$HOME" | tail -1)          # e.g. /dev/sda1
    DISK=$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1) # parent disk, e.g. sda
    [ -z "$DISK" ] && DISK=$(basename "$SRC" | sed 's/[0-9]*$//')
    DEVNUM=$(lsblk -no MAJ:MIN "/dev/$DISK" 2>/dev/null | head -1)
    echo "$DEVNUM rbps=$IO_RBPS" | sudo tee "$CG/io.max" >/dev/null
    echo "$DEVNUM rbps=$IO_RBPS" > "$OUT/meta/io.max.set"
fi
cat $CG/io.stat > "$OUT/meta/io.stat.before" 2>/dev/null || true

# --- lttng: curated v2 kernel profile (same families as collect_trace.sh) ---
sudo lttng destroy "$RUN" 2>/dev/null || true
sudo lttng create "$RUN" --output="$OUT/trace"
sudo lttng enable-event -k --syscall --all 2>/dev/null || true
for grp in 'sched_*' 'block_*' 'net_*' 'netif_*' 'napi_*' 'skb_*' 'sock_*' \
           'tcp_*' 'udp_*' 'irq_*' 'softirq_*' 'power_*' \
           'mm_vmscan_*' 'writeback_*' 'mm_compaction_*' 'mm_migrate_*'; do
    sudo lttng enable-event -k "$grp" 2>/dev/null || true
done
sudo lttng add-context -k -t pid -t tid -t procname
for ctx in cgroup_ns pid_ns net_ns mnt_ns ipc_ns user_ns; do
    sudo lttng add-context -k -t "$ctx" 2>/dev/null || true
done
sudo lttng list "$RUN" > "$OUT/meta/lttng_enabled.txt" 2>&1 || true
sudo lttng start

anchor() {
    python3 -c "import time,json,sys; print(json.dumps({'label':sys.argv[1],
        'realtime':time.clock_gettime(time.CLOCK_REALTIME),
        'monotonic':time.clock_gettime(time.CLOCK_MONOTONIC),
        'boottime':time.clock_gettime(time.CLOCK_BOOTTIME)}))" "$1"
}
# Problem #3: the task setup (dd) populates big.dat's page cache in the
# ROOT cgroup, so the reader would hit it for free and memory.high would
# never bite. Drop caches so the reader faults the file in from inside the
# capped cgroup -> its pages are charged there. Gated to memory runs only
# (a system-wide drop would add startup I/O noise to #1/#2).
if [ -n "$MEM_LIMIT" ] || [ -n "$IO_LIMIT" ]; then
    sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
fi

anchor start >> "$OUT/meta/clock_anchors.jsonl"

# --- agent runs in a subshell placed into the cgroup (parent stays out,
#     so lttng stop / cpu.stat reads are not charged to the agent) ---
set +e
(
    # capture first: `echo $BASHPID | ...` would report the pipe-subshell's
    # pid, not this subshell's, so the agent would never enter the cgroup.
    mypid=$BASHPID
    echo "$mypid" | sudo tee $CG/cgroup.procs >/dev/null
    echo "$mypid" > "$OUT/meta/root.pid"
    cd "$HOME/task"
    exec timeout "${AGENT_TIMEOUT:-900}" "$CLAUDE" -p "$PROMPT" \
        --dangerously-skip-permissions
) > "$OUT/agent.log" 2>&1
AGENT_EXIT=$?
set -e

anchor end >> "$OUT/meta/clock_anchors.jsonl"
sudo lttng stop
sudo lttng destroy "$RUN"
cat $CG/cpu.stat > "$OUT/meta/cpu.stat.after"
cat $CG/memory.events > "$OUT/meta/memory.events.after" 2>/dev/null || true
cat $CG/memory.stat   > "$OUT/meta/memory.stat.after"   2>/dev/null || true
cat $CG/memory.peak   > "$OUT/meta/memory.peak"         2>/dev/null || true
cat $CG/io.stat       > "$OUT/meta/io.stat.after"       2>/dev/null || true

# --- did the agent actually solve the task? ---
set +e
(cd "$HOME/task" && bash .check) > "$OUT/meta/task_check.txt" 2>&1
CHECK_EXIT=$?
# integrity: the agent must not have edited the protected test file. If it
# did, the pass is invalid - flag it so the run can be discarded.
TAMPERED=$(cd "$HOME/task" && git diff --name-only HEAD -- 'test_*.py' | head -1)
[ -z "$TAMPERED" ] && TAMPER=false || TAMPER=true
(cd "$HOME/task" && git diff --stat HEAD) > "$OUT/meta/agent_diff.txt" 2>&1
set -e

cat > "$OUT/meta/ground_truth.json" <<EOF
{ "run": "$RUN", "task": "$TASK", "cpu_max": "$CAP", "task_arg": "$TASK_ARG",
  "mem_limit": "$MEM_LIMIT", "io_limit": "$IO_LIMIT",
  "agent_exit": $AGENT_EXIT, "task_check_exit": $CHECK_EXIT,
  "test_file_tampered": $TAMPER,
  "kernel": "$(uname -r)", "nproc": $(nproc), "host": "$(hostname)",
  "claude_version": "$("$CLAUDE" --version 2>/dev/null | head -1)" }
EOF

sudo chown -R "$(id -u):$(id -g)" "$OUT"
echo "[$RUN] agent_exit=$AGENT_EXIT task_check=$CHECK_EXIT trace=$(du -sh "$OUT/trace" | cut -f1)"
