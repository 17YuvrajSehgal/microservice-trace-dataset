#!/bin/bash
# Campaign driver: tasks x caps x reps, shuffled order, resumable.
#   ./run_campaign.sh [reps]            (default 5)
#   TASKS="t1_toy.sh t2_medium.sh" ./run_campaign.sh 3
# Skips runs whose output dir already exists, so re-running resumes.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPS=${1:-5}
TASKS=${TASKS:-t2_medium.sh}
CAPS=("max" "100000 100000" "50000 100000" "25000 100000")
CAPNAMES=(nocap cap100 cap50 cap25)
BASE=${RUNS_DIR:-$HOME/runs}
MANIFEST=$BASE/manifest.csv
mkdir -p "$BASE"
[ -f "$MANIFEST" ] || echo "run,task,cap_name,cpu_max,rep,finished_at" > "$MANIFEST"

plan=()
for t in $TASKS; do
    for i in 0 1 2 3; do
        for r in $(seq 1 "$REPS"); do plan+=("$t|$i|$r"); done
    done
done
mapfile -t plan < <(printf '%s\n' "${plan[@]}" | shuf)

echo "campaign: ${#plan[@]} runs planned"
n=0
for item in "${plan[@]}"; do
    IFS='|' read -r t i r <<< "$item"
    run="${t%.sh}_${CAPNAMES[$i]}_r${r}"
    n=$((n + 1))
    if [ -d "$BASE/$run" ]; then
        echo "[$n/${#plan[@]}] skip $run (exists)"
        continue
    fi
    echo "[$n/${#plan[@]}] === $run (cpu.max='${CAPS[$i]}') ==="
    bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" "${CAPS[$i]}" "$t"
    echo "$run,$t,${CAPNAMES[$i]},${CAPS[$i]},$r,$(date -Is)" >> "$MANIFEST"
    sleep 10   # settle between runs
done
echo "campaign complete: $(ls -d "$BASE"/*/ | wc -l) run dirs, manifest: $MANIFEST"
