#!/bin/bash
# One-command Train Ticket gate / normal-sample driver: collect a full four-modality bundle
# (kernel + UST + OTLP traces + logs + metrics) under the TT booking load, then run the
# cross-modality alignment audit. The Train Ticket analogue of run_gate.sh - it reuses the SAME
# shared collection tooling (collect_trace.sh, download_metrics_full.sh, audit_alignment.py) and
# only supplies the TT-specific wiring via env: TT container regex, TT OTLP span file, TT booking
# load generator, and the :8080 front door (Sock Shop is :80).
#
#   ./run_gate_tt.sh [run_id] [duration_s] [users]
#
# collect_trace.sh self-heals stale LTTng state (its pre-flight). For a long unattended run over
# flaky SSH: nohup ./run_gate_tt.sh tt_gateNN > /tmp/tt_gateNN.out 2>&1 &
set -uo pipefail
TTD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)                 # train-ticket-collection-scripts
STRATA_REPO="${STRATA_REPO:-$(cd "$TTD/.." && pwd)}"
SD="$STRATA_REPO/microservice-lttng-data-collection-scripts"     # shared collection tooling
export TRACE_SCRIPTS_DIR="$SD"
RUN="${1:-tt_gate}"
DURATION="${2:-60}"
USERS="${3:-20}"
PROFILE="${PROFILE:-steady}"
PROM="${PROMETHEUS:-http://localhost:9090}"
FRONTEND="${FRONTEND_HOST:-http://localhost:8080}"

# TT app profile for the shared collect_trace.sh (container snapshots + LTTng session name) and
# for the downstream derivers (service_map). Sock Shop defaults stay untouched when these are unset.
export TRACE_APP=trainticket
export STRATATRACE_APP=trainticket
export CONTAINER_REGEX='trainticket_.*_1|^mysql$|^nacos$'
export LOG_CONTAINER_REGEX='trainticket_.*_1|^mysql$|^nacos$|^otel-collector$'
# TT spans are written by the TT otel-collector into the TT scripts dir, not the Sock Shop one.
export OTLP_SRC="$TTD/otlp-out/spans.jsonl"

# Pre-run health: Prometheus must be up or the metrics modality is silently empty.
if ! curl -sf -m 8 "$PROM/api/v1/query?query=up" >/dev/null 2>&1; then
    echo "WARNING: Prometheus unreachable at $PROM - metrics will be EMPTY."
    echo "  Fix: sudo docker start prometheus"
fi

rm -rf "$HOME/traces/normal/$RUN" "$HOME/${RUN}_metrics"

( cd "$SD" && ./collect_trace.sh normal "$RUN" "$DURATION" ) &
TP=$!
sleep 10   # let tracing settle before load
python3 "$TTD/load_generator.py" --host "$FRONTEND" --users "$USERS" \
    --duration "$((DURATION > 14 ? DURATION - 12 : 5))" --profile "$PROFILE" \
    --think-min 0.1 --think-max 0.3 \
    --output "$HOME/${RUN}_load.csv" || true
wait "$TP"

# Metrics for the exact run window (from the clock-anchored runinfo snapshots).
S=$(grep timestamp_utc "$HOME/traces/normal/$RUN/meta/runinfo_start.txt" 2>/dev/null | cut -d= -f2)
E=$(grep timestamp_utc "$HOME/traces/normal/$RUN/meta/runinfo_end.txt" 2>/dev/null | cut -d= -f2)
PROMETHEUS="$PROM" STEP=5s "$SD/download_metrics_full.sh" "$S" "$E" "$HOME/${RUN}_metrics" || true

# Cross-modality alignment audit (expect six OK lines).
python3 "$SD/audit_alignment.py" "$HOME/traces/normal/$RUN" \
    --load-csv "$HOME/${RUN}_load.csv" --metrics-dir "$HOME/${RUN}_metrics"
