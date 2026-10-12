#!/usr/bin/env bash
# extract_slice.sh - cut one time slice out of a kernel trace and keep only
# the scheduling events. The output file is the input for sched_budget.py
# and rhythm.py.
#
# Usage:
#   bash extract_slice.sh <run_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file>
#
# Example (a 10 second slice that starts at 15:19:10 UTC):
#   bash extract_slice.sh ~/run_A 2026-09-05 15:19:10 10 ~/work/baseline_slice.txt
#
# Notes:
#   - Times are UTC (the script uses babeltrace2 --clock-gmt).
#   - The slice must not cross midnight.
#   - A 10 second slice of a large trace can take a few minutes.
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: $0 <run_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file>" >&2
  exit 1
fi

run="$1"; day="$2"; start="$3"; secs="$4"; out="$5"
end=$(date -u -d "$day $start + $secs seconds" +%H:%M:%S)

mkdir -p "$(dirname "$out")"
babeltrace2 --clock-gmt --begin "$day $start" --end "$day $end" "$run/kernel/kernel" 2>/dev/null \
  | { grep -E 'sched_switch|sched_waking|sched_wakeup' || true; } > "$out"

echo "slice $day $start to $end UTC -> $out"
wc -l "$out"
