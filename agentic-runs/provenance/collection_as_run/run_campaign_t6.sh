#!/bin/bash
# Problem #3 campaigns. Two modes (Part A recoverable / Part B OOM cliff).
#   PART=A ./run_campaign_t6.sh [reps]   # memory.high dose-response (default)
#   PART=B ./run_campaign_t6.sh [reps]   # memory.max OOM cliff
# Caps are passed as absolute cgroup values in LIMITS (set after the
# profiling run tells you baseline B and you pick levels vs file F).
# Runs land in ~/runs_t6 with own manifest. Resumable.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPS=${1:-5}
PART=${PART:-A}
F_MB=${F_MB:-1024}                      # workload file size (constant)
BASE=${RUNS_DIR:-$HOME/runs_t6}
MANIFEST=$BASE/manifest.csv
mkdir -p "$BASE"
[ -f "$MANIFEST" ] || echo "run,task,part,mem_limit,rep,finished_at" > "$MANIFEST"

# high:max = soft cap effectively unlimited, but still triggers the
# drop_caches path so every cell faults the file in-cgroup (comparable).
if [ "$PART" = "A" ]; then
    # measured knee: agent ~0.3G + 1G file ~= 1.38G. Straddle it.
    LIMITS=${LIMITS:-"high:max high:1536M high:1152M high:768M"}  # roomy..tight
else
    REPS=${1:-3}
    LIMITS=${LIMITS:-"max:2G max:1280M max:1024M max:768M"}     # down toward B
fi

plan=()
i=0
for lim in $LIMITS; do
    for r in $(seq 1 "$REPS"); do plan+=("$i|$lim|$r"); done
    i=$((i + 1))
done
mapfile -t plan < <(printf '%s\n' "${plan[@]}" | shuf)

echo "t6 Part $PART: ${#plan[@]} runs planned (F=${F_MB}MB)"
n=0
for item in "${plan[@]}"; do
    IFS='|' read -r idx lim r <<< "$item"
    tag=$(echo "$lim" | tr ':' '_' | tr -d 'GM')   # e.g. high_3 / high_max
    run="t6${PART}_${tag}_r${r}"
    n=$((n + 1))
    if [ -d "$BASE/$run" ]; then echo "[$n/${#plan[@]}] skip $run"; continue; fi
    echo "[$n/${#plan[@]}] === $run (mem=$lim) ==="
    RUNS_DIR=$BASE bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" max t6_memtouch.sh "$F_MB" "$lim"
    echo "$run,t6_memtouch.sh,$PART,$lim,$r,$(date -Is)" >> "$MANIFEST"
    sleep 10
done
echo "t6 Part $PART complete"
