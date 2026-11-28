#!/bin/bash
# collect_v4.sh - one v4 run: a small program that has (or does not have) one problem, traced with
# the same LTTng kernel profile as v2 and v3.
#
#   collect_v4.sh <problem> <language> <fault|healthy> <repeat>
#
# Timeline (seconds): start noise and the program, settle SETTLE_S, start the kernel trace,
# BASELINE_S healthy, then FAULT_S with the fault switched on (or, in a healthy run, nothing
# switched on - the same times are written to the ground truth so the same windows can be cut),
# then RECOVERY_S, stop. The program prints one stats line per second; those lines are the run's
# logs, and verify_v4.py compares them before and during the fault.
#
# Output: ~/archive/runs/v4_<problem>/v4_<problem>_<lang>_<mode>_r<repeat>/ with kernel/ (CTF,
# gzipped), logs/, metrics.csv, meta/, ground_truth.json, verification.json, SHA256SUMS. The folder
# name fits transfer/export_recipe.sh, so pull_from_vm.sh moves v4 like v3.
set -uo pipefail
PROBLEM="${1:?problem}"; LANG_="${2:?language}"; MODE="${3:?fault|healthy}"; REP="${4:?repeat}"
V4="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTLE_S="${SETTLE_S:-20}"; BASELINE_S="${BASELINE_S:-60}"; FAULT_S="${FAULT_S:-90}"; RECOVERY_S="${RECOVERY_S:-45}"
FAM="v4_${PROBLEM}"; RUN="${FAM}_${LANG_}_${MODE}_r${REP}"
OUT="$HOME/traces/$FAM/$RUN"; ARCH="${V4_ARCHIVE:-$HOME/archive/runs}/$FAM"
export V4_FLAG=/dev/shm/v4_fault V4_TIDS=/dev/shm/v4_tids V4_LANG="$LANG_"
utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$RUN] $*"; }

[[ "$MODE" == fault || "$MODE" == healthy ]] || { echo "mode must be fault or healthy"; exit 1; }
# shellcheck source=/dev/null
source "$V4/lib/common.sh"
# shellcheck source=/dev/null
source "$V4/problems/$PROBLEM/problem.sh" || { echo "no problem $PROBLEM"; exit 1; }
[[ " $LANGS " == *" $LANG_ "* ]] || { echo "$PROBLEM has no $LANG_ program (languages: $LANGS)"; exit 1; }
# A problem may check a different number in one language (KPI_python=done ...): see lock_contention.
eval "KPI=\${KPI_${LANG_}:-\$KPI}; KPI_DIR=\${KPI_DIR_${LANG_}:-\$KPI_DIR}; KPI_FACTOR=\${KPI_FACTOR_${LANG_}:-\$KPI_FACTOR}"
[[ -d "$ARCH/$RUN" ]] && { log "already collected - skipped"; exit 0; }

rm -rf "$OUT"; mkdir -p "$OUT/logs" "$OUT/meta" "$ARCH"
rm -f "$V4_FLAG" "$V4_TIDS"
sudo lttng destroy -a > /dev/null 2>&1 || true
declare -F setup_run > /dev/null && setup_run

# --- background noise and the program ---------------------------------------------------------
bash "$V4/lib/noise.sh" start "$OUT/logs"
CMD="$(program_cmd "$LANG_")"
PIN="${PIN_CPU:-}"
log "program: ${PIN:+taskset -c $PIN }$CMD"
cd "$V4/build/$PROBLEM/$LANG_" || { echo "not built: $V4/build/$PROBLEM/$LANG_"; exit 1; }
# shellcheck disable=SC2086
setsid bash -c "exec ${PIN:+taskset -c $PIN }$CMD" > >(python3 -u "$V4/lib/stamp.py" > "$OUT/logs/program.log") 2>&1 &
PID=$!
cd - > /dev/null
sleep 2
kill -0 "$PID" 2>/dev/null || { log "the program died at start:"; tail -5 "$OUT/logs/program.log"; bash "$V4/lib/noise.sh" stop; exit 1; }
declare -F post_start > /dev/null && post_start "$PID"
python3 -u "$V4/lib/sampler.py" "$PID" > "$OUT/metrics.csv" 2> "$OUT/logs/sampler.err" &
SAMPLER=$!
sleep "$SETTLE_S"

# --- kernel trace (the v3 profile: all syscalls + these tracepoint groups, 8M x 32 per CPU) ----
sudo lttng create "$RUN" --output="$OUT/kernel" > /dev/null
sudo lttng enable-channel -k channel0 --subbuf-size="${KERNEL_SUBBUF_SIZE:-8M}" --num-subbuf="${KERNEL_NUM_SUBBUF:-32}" > /dev/null
sudo lttng enable-event -k --syscall --all --channel channel0 > /dev/null 2>&1 || true
for grp in sched_* block_* net_* netif_* napi_* skb_* sock_* tcp_* udp_* irq_* softirq_* power_*; do
    sudo lttng enable-event -k "$grp" --channel channel0 > /dev/null 2>&1 || true
done
sudo lttng add-context --kernel --channel channel0 --type=pid --type=tid --type=procname > /dev/null 2>&1 || true
for ctx in cgroup_ns pid_ns net_ns mnt_ns ipc_ns user_ns; do
    sudo lttng add-context --kernel --channel channel0 --type="$ctx" > /dev/null 2>&1 || true
done
sudo lttng list "$RUN" > "$OUT/meta/lttng_enabled_kernel.txt" 2>&1
clocks() { python3 -c "import time; print('realtime', time.clock_gettime(time.CLOCK_REALTIME), 'monotonic', time.clock_gettime(time.CLOCK_MONOTONIC), 'boottime', time.clock_gettime(time.CLOCK_BOOTTIME))"; }
sudo lttng start > /dev/null
TRACE_START=$(utc); clocks > "$OUT/meta/clocks_start.txt"
log "tracing from $TRACE_START ($MODE)"

sleep "$BASELINE_S"
FAULT_START=$(utc)
if [[ "$MODE" == fault ]]; then
    if declare -F inject_fault > /dev/null; then inject_fault "$PID" "$OUT"; else touch "$V4_FLAG"; fi
    log "fault ON at $FAULT_START"
fi
sleep "$FAULT_S"
FAULT_END=$(utc)
if [[ "$MODE" == fault ]]; then
    if declare -F cleanup_fault > /dev/null; then cleanup_fault "$PID" "$OUT"; else rm -f "$V4_FLAG"; fi
    log "fault OFF at $FAULT_END"
fi
sleep "$RECOVERY_S"

STOP=$(sudo lttng stop 2>&1); clocks > "$OUT/meta/clocks_end.txt"
sudo lttng destroy > /dev/null 2>&1 || true
TRACE_END=$(utc)
LOSS=$(echo "$STOP" | grep -oiE '[0-9]+ events? (were|was) discarded|[0-9]+ packets? (were|was) lost' | tr '\n' ';')
echo "$STOP" > "$OUT/meta/lttng_stop.txt"

kill "$SAMPLER" 2>/dev/null
kill -TERM -- "-$PID" 2>/dev/null; kill -TERM "$PID" 2>/dev/null; sleep 2
kill -KILL -- "-$PID" 2>/dev/null; kill -KILL "$PID" 2>/dev/null   # a deadlocked program does not exit on TERM
declare -F cleanup_fault > /dev/null && [[ "$MODE" == fault ]] && cleanup_fault "$PID" "$OUT" > /dev/null 2>&1
rm -f "$V4_FLAG"
bash "$V4/lib/noise.sh" stop
[[ -f "$V4_TIDS" ]] && cp "$V4_TIDS" "$OUT/meta/tids.txt"

# --- ground truth, check, package ---------------------------------------------------------------
python3 - "$OUT/ground_truth.json" <<PY
import json, sys
json.dump({"fault": {"family": "$FAM", "name": "$PROBLEM", "language": "$LANG_", "mode": "$MODE",
                     "candidate": "$CAND", "mechanism": """$MECH""", "target_process": "$(program_comm "$LANG_")",
                     "pid": $PID, "pinned_cpu": "${PIN:-${ROLE_CPU:-none}}",
                     "injection_start_utc": "$FAULT_START", "injection_end_utc": "$FAULT_END",
                     "note": "in a healthy run nothing was switched on; the times mark the same windows"},
           "remediation": {"action": """$REMEDIATION"""}, "trace": {"start_utc": "$TRACE_START", "end_utc": "$TRACE_END"},
           "event_loss": "${LOSS:-none}"}, open(sys.argv[1], "w"), indent=2)
PY
python3 "$V4/lib/verify_v4.py" "$OUT" "$KPI" "$KPI_DIR" "$KPI_FACTOR" "${KPI_STAT:-median}" > "$OUT/verification.json"
VERDICT=$(python3 -c "import json; print(json.load(open('$OUT/verification.json'))['verdict'])")
sudo chown -R "$USER" "$OUT"
find "$OUT/kernel" -type f ! -name metadata ! -path '*/index/*' -size +1M -print0 | xargs -0 -r pigz -p 6
(cd "$OUT" && find . -type f ! -path './kernel/*' -size -8M -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
mv "$OUT" "$ARCH/$RUN"
echo "$RUN,$FAM,$LANG_,$MODE,$REP,$VERDICT,${LOSS:-clean},$(utc)" >> "${V4_MANIFEST:-$HOME/v4_manifest.csv}"
log "DONE verification=$VERDICT event_loss=${LOSS:-clean} size=$(du -sh "$ARCH/$RUN" | cut -f1)"
