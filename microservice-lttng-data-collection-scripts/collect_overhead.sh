#!/bin/bash
# collect_overhead.sh - RQ4-i: measured collection overhead, fair (rotated-order)
# protocol. Wraps the existing condition harness scripts with per-repeat order
# rotation for fairness. This is the "rare asset" no peer dataset ships.
#
# Conditions:
#   baseline    - load only, no collection
#   lttng_only  - + kernel tracing (the expensive modality; the headline cost)
#   lmat_async  - + async LMAT analysis (the JSS mitigation: ~+13% P95 vs baseline)
# (metrics/logs/otel are cheap, standard collection; the interesting cost is the
#  kernel - lttng_only vs baseline is the RQ4 headline. Finer per-modality split
#  is a v2 extension.)
#
#   ./collect_overhead.sh [--no-lmat] [--dry-run]
#   env: USERS(200) REPEATS(3) DURATION(100) COOLDOWN_S(20) EXPERIMENT_ROOT
#        FRONTEND_HOST  MODEL_PATH/VOCAB_PATH/DELAY_PATH (lmat_async; auto-detected)
#
# Run on the VM with the Sock Shop stack UP. Analyze at the end with
# analyse_reviewer_overhead.py.
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
USERS="${USERS:-200}"; REPEATS="${REPEATS:-3}"; DURATION="${DURATION:-100}"
COOLDOWN_S="${COOLDOWN_S:-20}"; QUIET_FLAG="${QUIET_FLAG:---quiet}"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-$HOME/experiments/overhead_wave2}"
export FRONTEND_HOST="${FRONTEND_HOST:-http://localhost:80}"

DRY=0; NOLMAT=0
for a in "$@"; do case "$a" in --dry-run|-n) DRY=1 ;; --no-lmat) NOLMAT=1 ;; esac; done

# auto-detect the LMAT model for the analysis-overhead condition
if [ -z "${MODEL_PATH:-}" ]; then
  MODEL_PATH=$(ls "$SD"/../logs/lstm_*/model_best.pt "$HOME"/adaptive_tracer/logs/lstm_*/model_best.pt 2>/dev/null | head -1 || true)
fi
CONDITIONS="baseline lttng_only lmat_async"
if [ "$NOLMAT" = 1 ] || [ -z "${MODEL_PATH:-}" ]; then
  CONDITIONS="baseline lttng_only"
  echo "[overhead] LMAT model not found / --no-lmat -> conditions: $CONDITIONS (kernel-overhead measurement)"
fi
export MODEL_PATH="${MODEL_PATH:-}" VOCAB_PATH="${VOCAB_PATH:-}" DELAY_PATH="${DELAY_PATH:-}" EXPERIMENT_ROOT

mkdir -p "$EXPERIMENT_ROOT"
MANIFEST="$EXPERIMENT_ROOT/run_manifest.csv"
[ -f "$MANIFEST" ] || echo "condition,users,repeat,run_id,duration_s,started_utc,ended_utc" > "$MANIFEST"

arr=($CONDITIONS); NC=${#arr[@]}
echo "=== overhead plan: users=$USERS repeats=$REPEATS duration=${DURATION}s conditions=[$CONDITIONS] ==="
echo "    ~$(( REPEATS * NC * (DURATION + 30 + COOLDOWN_S) / 60 )) min"
[ "$DRY" = 1 ] && { echo "(dry-run) nothing executed."; exit 0; }

run_one() {
  local c="$1" rid="$2" s e
  s=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  export LOAD_USERS="$USERS" THINK_MIN="${THINK_MIN:-0.2}" THINK_MAX="${THINK_MAX:-1.0}"
  echo ">>> condition=$c run_id=$rid"
  case "$c" in
    baseline)   "$SD/baseline_load.sh"  "$rid" "$DURATION" ;;
    lttng_only) "$SD/lttng_only_run.sh" "$rid" "$DURATION" "$QUIET_FLAG" ;;
    lmat_async) "$SD/lmat_async_run.sh" "$rid" "$DURATION" "$QUIET_FLAG" ;;
    *) echo "unknown condition $c"; return 1 ;;
  esac
  e=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "$c,$USERS,$REP,$rid,$DURATION,$s,$e" >> "$MANIFEST"
}

for REP in $(seq 1 "$REPEATS"); do
  off=$(( (REP - 1) % NC )); order=()
  for k in $(seq 0 $((NC - 1))); do order+=("${arr[$(((k + off) % NC))]}"); done
  echo "--- repeat $REP order: ${order[*]} ---"
  for c in "${order[@]}"; do
    run_one "$c" "$(printf u%03d_r%02d "$USERS" "$REP")" || echo "[overhead] $c returned nonzero"
    [ "$COOLDOWN_S" -gt 0 ] && sleep "$COOLDOWN_S"
  done
done

echo "=== analyze ==="
python3 "$SD/analyse_reviewer_overhead.py" --experiment_root "$EXPERIMENT_ROOT" --reference_users "$USERS" 2>&1 | tail -30 \
  || echo "(analyzer not run; load CSVs are under $EXPERIMENT_ROOT)"
echo "=== overhead done -> $EXPERIMENT_ROOT ==="
