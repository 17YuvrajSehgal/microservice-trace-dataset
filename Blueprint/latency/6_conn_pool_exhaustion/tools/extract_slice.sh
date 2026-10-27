#!/usr/bin/env bash
# extract_slice.sh - cut one time slice out of a kernel trace and keep only
# the scheduling events (sched_switch, sched_waking, sched_wakeup).
# The output file is the input for sched_budget.py, rhythm.py,
# victim_info.py and wake_graph.py.
#
# Usage:
#   bash extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file>
#
#   <trace_dir>  the folder that holds the trace: the `metadata` file, the
#                channel data files, and the `index/` folder
#   <YYYY-MM-DD> <HH:MM:SS>  start of the slice, in UTC
#   <seconds>    length of the slice
#   <out_file>   text file to write
#
# How it works:
#   1. idx_slice.py copies only the packets that cover the window into a small
#      temporary trace, using index/*.idx. This keeps the time short wherever
#      the slice sits in the trace.
#   2. babeltrace2 reads the small trace and trims it to the exact window.
#   If the trace has no index/ folder, it reads the whole trace instead. That
#   works, but it gets slower the later the slice is.
#
# Notes:
#   - Times are UTC (babeltrace2 --clock-gmt). A slice may cross midnight.
#   - idx_slice.py must be in the same folder as this script.
#   - The temporary trace is <out_file>.mini. It is deleted at the end.
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: $0 <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file>" >&2
  exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
trace="$1"; day="$2"; start="$3"; secs="$4"; out="$5"
# "UTC" must be written out: without it, some versions of date read "+ N" as a time zone
# Self-heal a missing/placeholder date (the agent sometimes calls this before idx_summary):
# resolve the day from the trace itself - the same source idx_summary reads - so the slice
# still cuts instead of failing on a bad date.
trace_day="$(python3 "$here/idx_summary.py" "$trace" 2>/dev/null | awk '/^date \(UTC\)/{print $4}')"
if [ -n "$trace_day" ] && [ "$day" != "$trace_day" ]; then
  # malformed OR simply wrong (a guessed date slices an empty window and reads as "no data")
  echo "note: date '$day' is not the trace's own date; using $trace_day" >&2
  day="$trace_day"
elif [ -z "$trace_day" ] && ! printf '%s' "$day" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
  echo "error: bad date '$day' and could not resolve the trace date from idx_summary" >&2
  exit 1
fi
end=$(date -u -d "$day $start UTC + $secs seconds" '+%Y-%m-%d %H:%M:%S')

if [ ! -f "$trace/metadata" ]; then
  echo "error: $trace has no metadata file. Give the folder that holds the trace itself." >&2
  exit 1
fi

mkdir -p "$(dirname "$out")"

if ls "$trace"/index/*.idx >/dev/null 2>&1; then
  mini="$out.mini"
  rm -rf "$mini"
  trap 'rm -rf "$mini"' EXIT
  python3 "$here/idx_slice.py" "$trace" "$day $start" "$end" "$mini" > /dev/null
  src="$mini"
else
  echo "note: no index/ folder, reading the whole trace (slow)" >&2
  src="$trace"
fi

"${BT2:-babeltrace2}" --clock-gmt --begin "$day $start" --end "$end" "$src" 2>/dev/null \
  | { grep -E 'sched_switch|sched_waking|sched_wakeup' || true; } > "$out"

echo "slice $day $start to $end UTC -> $out"
wc -l "$out"
