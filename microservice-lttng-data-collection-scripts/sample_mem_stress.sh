#!/bin/bash
set -e

if ! command -v stress-ng >/dev/null 2>&1; then
  echo "ERROR: stress-ng is not installed or not on PATH. Memory anomaly cannot be injected." >&2
  exit 1
fi

RUN_ID=${1:-sample}
DURATION=${2:-30}
EXPERIMENT_DIR=~/experiments/anomaly_mem/$RUN_ID
FRONTEND_HOST=${FRONTEND_HOST:-http://localhost:80}
LOAD_USERS=${LOAD_USERS:-200}
THINK_MIN=${THINK_MIN:-0.1}
THINK_MAX=${THINK_MAX:-0.3}

# Memory pressure knobs — moderated for a sample so the box does not OOM while
# the (large) LTTng ring buffers are also resident. Tune up for full runs.
VM_WORKERS=${VM_WORKERS:-12}
VM_BYTES=${VM_BYTES:-50%}
VM_METHOD=${VM_METHOD:-all}

mkdir -p "$EXPERIMENT_DIR"/{metrics,load_logs}
RUN_LOG="$EXPERIMENT_DIR/run.log"
exec > >(tee -a "$RUN_LOG") 2>&1

echo "🧠 SAMPLE MEM Stress: $RUN_ID (${DURATION}s, ${LOAD_USERS} users, vm=${VM_WORKERS}, bytes=${VM_BYTES})"

sudo -v
echo "⏳ Short warmup for Prometheus/service stability (5s)..."
sleep 5

RUN_START_EPOCH=$(date -u +%s)

# 1) Tracing
(cd ~ && ./collect_trace.sh anomaly_mem "$RUN_ID" "$DURATION") &
TRACE_PID=$!

# 2) Memory stress (allocate + touch + keep resident)
stress-ng \
  --vm "$VM_WORKERS" \
  --vm-bytes "$VM_BYTES" \
  --vm-method "$VM_METHOD" \
  --vm-keep \
  --page-in \
  --timeout "${DURATION}s" \
  --metrics-brief &
STRESS_PID=$!

echo "🔥 Memory pressure PID $STRESS_PID"

sleep 2
if ! kill -0 "$STRESS_PID" 2>/dev/null; then
  echo "ERROR: stress-ng exited immediately. Memory anomaly was not injected." >&2
  wait "$STRESS_PID" || true
  exit 1
fi

# 3) Load
python3 ~/load_generator.py \
  --host "${FRONTEND_HOST:-http://localhost:80}" \
  --users "$LOAD_USERS" \
  --duration "$DURATION" \
  --think-min "$THINK_MIN" \
  --think-max "$THINK_MAX" \
  --log-level DEBUG \
  --output "$EXPERIMENT_DIR/load_results.csv" &
LOAD_PID=$!

wait "$TRACE_PID" "$STRESS_PID" "$LOAD_PID"

RUN_END_EPOCH=$(date -u +%s)

# Cleanup
TRACE_DIR=~/traces/anomaly_mem/"$RUN_ID"
sudo chown -R "$(whoami)" "$TRACE_DIR" 2>/dev/null || true

echo "⏸️  Prometheus flush (10s)..."
sleep 10

START_ISO=$(date -u -d "@$((RUN_START_EPOCH-10))" '+%Y-%m-%dT%H:%M:%SZ')
END_ISO=$(date -u -d "@$((RUN_END_EPOCH+10))" '+%Y-%m-%dT%H:%M:%SZ')

STEP=10s RATE_WINDOW=1m ./download_metrics.sh "$START_ISO" "$END_ISO" "$EXPERIMENT_DIR/metrics" || true

# Summary
REQ_COUNT=$(tail -n +2 "$EXPERIMENT_DIR/load_results.csv" 2>/dev/null | wc -l || echo 0)
OTEL_SPANS=$(babeltrace "$TRACE_DIR/ust" 2>/dev/null | grep -c "otel.spans" || echo 0)
BUSINESS_SPANS=$(babeltrace "$TRACE_DIR/ust" 2>/dev/null | grep -c -i "service=carts\|service=orders\|service=shipping\|service=queue-master" || echo 0)

cat << EOF

✅ $RUN_ID COMPLETE
📊 Requests: $REQ_COUNT
🔍 Spans: $OTEL_SPANS ($BUSINESS_SPANS business)
📈 Metrics: $(find "$EXPERIMENT_DIR/metrics" -type f | wc -l) files
💾 $(du -sh "$EXPERIMENT_DIR" 2>/dev/null | cut -f1)
💾 $(du -sh "$TRACE_DIR" 2>/dev/null | cut -f1)

EOF
