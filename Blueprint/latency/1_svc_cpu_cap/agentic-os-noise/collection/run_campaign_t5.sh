#!/bin/bash
# Problem #2 Part B campaign: N sub-agents via Task tool, uncapped.
#   ./run_campaign_t5.sh [reps]      (default 3);  NS="4 8" by default.
# Runs land in ~/runs_t5 with own manifest. Resumable.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPS=${1:-3}
NS=${NS:-"4 8"}
BASE=${RUNS_DIR:-$HOME/runs_t5}
MANIFEST=$BASE/manifest.csv
mkdir -p "$BASE"
[ -f "$MANIFEST" ] || echo "run,task,N,rep,finished_at" > "$MANIFEST"

plan=()
for nn in $NS; do for r in $(seq 1 "$REPS"); do plan+=("$nn|$r"); done; done
mapfile -t plan < <(printf '%s\n' "${plan[@]}" | shuf)

echo "t5 campaign: ${#plan[@]} runs planned"
n=0
for item in "${plan[@]}"; do
    IFS='|' read -r nn r <<< "$item"
    run="t5_n${nn}_r${r}"
    n=$((n + 1))
    if [ -d "$BASE/$run" ]; then
        echo "[$n/${#plan[@]}] skip $run (exists)"; continue
    fi
    echo "[$n/${#plan[@]}] === $run (N=$nn) ==="
    RUNS_DIR=$BASE bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" max t5_subagents.sh "$nn"
    echo "$run,t5_subagents.sh,$nn,$r,$(date -Is)" >> "$MANIFEST"
    sleep 10
done
echo "t5 campaign complete"
