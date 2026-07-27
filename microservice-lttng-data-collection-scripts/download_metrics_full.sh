#!/usr/bin/env bash
# Full-fidelity Prometheus export for the metrics modality.
#
# Unlike download_metrics.sh (which exports a curated ~33-series KPI view),
# this script enumerates EVERY metric name present in the run window and
# exports the complete query_range response (all series / label combinations
# of each metric), gzipped, one file per metric name.
#
# Usage:
#   PROMETHEUS=http://localhost:9090 ./download_metrics_full.sh <start> <end> [output_dir]
#
# <start>/<end> accept anything GNU date -d understands (ISO-8601 or epoch@).
set -u
set -o pipefail

PROMETHEUS="${PROMETHEUS:-http://localhost:9090}"
# 5s matches the Sock Shop Prometheus scrape interval: full native resolution.
STEP="${STEP:-5s}"

usage() {
    cat <<EOF
Usage: $0 <start> <end> [output_dir]
EOF
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "❌ Required command not found: $1"
        exit 1
    }
}

require_cmd date
require_cmd curl
require_cmd gzip
require_cmd wc
require_cmd du

HAS_JQ=0
if command -v jq >/dev/null 2>&1; then
    HAS_JQ=1
fi

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    usage
fi

START_RAW=$1
END_RAW=$2
OUTPUT_DIR=${3:-metrics_full}

START=$(date -u -d "$START_RAW" +%s 2>/dev/null) || {
    echo "❌ Invalid start time: $START_RAW"
    exit 1
}

END=$(date -u -d "$END_RAW" +%s 2>/dev/null) || {
    echo "❌ Invalid end time: $END_RAW"
    exit 1
}

if [ "$START" -ge "$END" ]; then
    echo "❌ Start time must be earlier than end time"
    exit 1
fi

mkdir -p "$OUTPUT_DIR" || {
    echo "❌ Could not create output directory: $OUTPUT_DIR"
    exit 1
}

echo "📥 Full export: $(date -u -d "@$START" '+%Y-%m-%d %H:%M:%S UTC') → $(date -u -d "@$END" '+%Y-%m-%d %H:%M:%S UTC')"
echo "🌐 Prometheus: $PROMETHEUS"
echo "📏 Step: $STEP"
echo "📁 Output dir: $OUTPUT_DIR/"
echo

echo "=== Enumerating metric names in window ==="
NAMES_TMP=$(mktemp)
HTTP_CODE=$(curl -sS -m 30 -w "%{http_code}" -o "$NAMES_TMP" -G \
    "$PROMETHEUS/api/v1/label/__name__/values" \
    --data-urlencode "start=$START" \
    --data-urlencode "end=$END")

if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Could not enumerate metric names. HTTP $HTTP_CODE"
    cat "$NAMES_TMP"
    rm -f "$NAMES_TMP"
    exit 1
fi

# tr -d '\r': jq on Windows (Git Bash) emits CRLF line endings; a stray CR in
# a metric name silently pollutes the output filename (name^M.json.gz) while
# Prometheus still accepts the query (CR parses as whitespace). Harmless on
# Linux, essential for portable reproduction.
if [ "$HAS_JQ" -eq 1 ]; then
    mapfile -t METRIC_NAMES < <(jq -r '.data[]' "$NAMES_TMP" | tr -d '\r')
else
    # Fallback without jq: metric names contain only [a-zA-Z0-9_:], so a crude
    # extraction of quoted tokens from the JSON array is safe.
    mapfile -t METRIC_NAMES < <(tr ',' '\n' < "$NAMES_TMP" | grep -oE '"[a-zA-Z_:][a-zA-Z0-9_:]*"' | tr -d '"\r' | grep -vE '^(success|data|status)$')
fi
rm -f "$NAMES_TMP"

TOTAL=${#METRIC_NAMES[@]}
if [ "$TOTAL" -eq 0 ]; then
    echo "❌ No metric names found in window"
    exit 1
fi
echo "✅ $TOTAL metric names"
echo

FAILED=0
EMPTY=0
DONE=0

for name in "${METRIC_NAMES[@]}"; do
    DONE=$((DONE + 1))
    file="$OUTPUT_DIR/${name}.json.gz"
    tmp=$(mktemp)

    http_code=$(curl -sS -m 120 -w "%{http_code}" -o "$tmp" -G \
        "$PROMETHEUS/api/v1/query_range" \
        --data-urlencode "query=$name" \
        --data-urlencode "start=$START" \
        --data-urlencode "end=$END" \
        --data-urlencode "step=$STEP")

    if [ "$http_code" != "200" ]; then
        echo "❌ [$DONE/$TOTAL] $name: HTTP $http_code"
        rm -f "$tmp"
        FAILED=$((FAILED + 1))
        continue
    fi

    if [ "$HAS_JQ" -eq 1 ]; then
        result_count=$(jq -r '(.data.result | length) // 0' "$tmp" 2>/dev/null)
        if [ "${result_count:-0}" -eq 0 ]; then
            EMPTY=$((EMPTY + 1))
        fi
    fi

    gzip -c "$tmp" > "$file"
    rm -f "$tmp"

    if [ $((DONE % 50)) -eq 0 ]; then
        echo "→ [$DONE/$TOTAL] ..."
    fi
done

FILE_COUNT=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*.json.gz' | wc -l | tr -d ' ')
DIR_SIZE=$(du -sh "$OUTPUT_DIR" | awk '{print $1}')

echo
echo "🎉 Complete: $FILE_COUNT/$TOTAL metrics exported, $EMPTY empty in window, $FAILED failed"
echo "💾 Directory size: $DIR_SIZE"

if [ "$FAILED" -gt 0 ]; then
    exit 2
fi
exit 0
