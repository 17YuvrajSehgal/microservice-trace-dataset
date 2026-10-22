#!/bin/bash
# Problem #2 Part A campaign: W workers vs 4 vCPUs, uncapped, shuffled,
# resumable.   ./run_campaign_t4.sh [reps]      (default 5)
#   WS="2 4 8 16" by default; runs land in ~/runs_t4 with own manifest.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPS=${1:-5}
WS=${WS:-"2 4 8 16"}
BASE=${RUNS_DIR:-$HOME/runs_t4}
MANIFEST=$BASE/manifest.csv
mkdir -p "$BASE"
[ -f "$MANIFEST" ] || echo "run,task,W,rep,finished_at" > "$MANIFEST"

plan=()
for w in $WS; do for r in $(seq 1 "$REPS"); do plan+=("$w|$r"); done; done
mapfile -t plan < <(printf '%s\n' "${plan[@]}" | shuf)

echo "t4 campaign: ${#plan[@]} runs planned"
n=0
for item in "${plan[@]}"; do
    IFS='|' read -r w r <<< "$item"
    run="t4_w${w}_r${r}"
    n=$((n + 1))
    if [ -d "$BASE/$run" ]; then
        echo "[$n/${#plan[@]}] skip $run (exists)"
        continue
    fi
    echo "[$n/${#plan[@]}] === $run (W=$w) ==="
    RUNS_DIR=$BASE bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" max t4_parallel.sh "$w"
    echo "$run,t4_parallel.sh,$w,$r,$(date -Is)" >> "$MANIFEST"
    sleep 10
done
echo "t4 campaign complete"
