#!/bin/bash
# One-command Phase-0 gate / normal-sample driver: collect a full
# four-modality bundle under load, then run the cross-modality audit.
# Proven end-to-end on the VM 2026-07-28 (all six audit lines OK).
#
#   ./run_gate.sh [run_id] [duration_s] [users]
#
# collect_trace.sh self-heals any stale LTTng state (its pre-flight), so no
# manual daemon reset is needed between runs. For a long unattended run over
# flaky SSH, wrap this in: nohup ./run_gate.sh gateNN > /tmp/gateNN.out 2>&1 &
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export TRACE_SCRIPTS_DIR="$SD"
RUN="${1:-gate}"
DURATION="${2:-40}"
USERS="${3:-50}"
PROM="${PROMETHEUS:-http://localhost:9090}"
FRONTEND="${FRONTEND_HOST:-http://localhost:80}"

# Pre-run health: Prometheus must be up or the metrics modality is silently
# empty (it has no restart policy upstream; see TROUBLESHOOTING.md).
if ! curl -sf -m 8 "$PROM/api/v1/query?query=up" >/dev/null 2>&1; then
    echo "WARNING: Prometheus unreachable at $PROM - metrics will be EMPTY."
    echo "  Fix: sudo docker start prometheus"
fi

rm -rf "$HOME/traces/normal/$RUN" "$HOME/${RUN}_metrics"

( cd "$SD" && ./collect_trace.sh normal "$RUN" "$DURATION" ) &
TP=$!
sleep 10   # let tracing settle before load
python3 "$SD/load_generator.py" --host "$FRONTEND" --users "$USERS" \
    --duration "$((DURATION > 14 ? DURATION - 12 : 5))" \
    --think-min 0.1 --think-max 0.3 \
    --output "$HOME/${RUN}_load.csv" || true
wait "$TP"

# Metrics for the exact run window (from the clock-anchored runinfo).
S=$(grep timestamp_utc "$HOME/traces/normal/$RUN/meta/runinfo_start.txt" 2>/dev/null | cut -d= -f2)
E=$(grep timestamp_utc "$HOME/traces/normal/$RUN/meta/runinfo_end.txt" 2>/dev/null | cut -d= -f2)
PROMETHEUS="$PROM" STEP=5s "$SD/download_metrics_full.sh" "$S" "$E" "$HOME/${RUN}_metrics" || true

# Audit runs after collect_trace has chowned the bundle (via wait above).
python3 "$SD/audit_alignment.py" "$HOME/traces/normal/$RUN" \
    --load-csv "$HOME/${RUN}_load.csv" --metrics-dir "$HOME/${RUN}_metrics"
