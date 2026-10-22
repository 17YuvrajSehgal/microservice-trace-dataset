#!/bin/bash
# Problem #4 campaign: io.max rbps dose-response, 1 GB single read.
#   ./run_campaign_t8.sh [reps]   (default 5)
# RBPS levels in LIMITS (bytes/s); "none" = uncapped (still drops caches).
# Runs land in ~/runs_t8 with own manifest. Resumable.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPS=${1:-5}
F_MB=${F_MB:-1024}
LIMITS=${LIMITS:-"none 209715200 104857600 52428800"}   # unltd,200M,100M,50M
BASE=${RUNS_DIR:-$HOME/runs_t8}
MANIFEST=$BASE/manifest.csv
mkdir -p "$BASE"
[ -f "$MANIFEST" ] || echo "run,task,rbps,rep,finished_at" > "$MANIFEST"

plan=()
for lim in $LIMITS; do for r in $(seq 1 "$REPS"); do plan+=("$lim|$r"); done; done
mapfile -t plan < <(printf '%s\n' "${plan[@]}" | shuf)

echo "t8 campaign: ${#plan[@]} runs planned (F=${F_MB}MB)"
n=0
for item in "${plan[@]}"; do
    IFS='|' read -r lim r <<< "$item"
    tag=$([ "$lim" = "none" ] && echo "unltd" || echo "$((lim/1048576))M")
    run="t8_${tag}_r${r}"
    n=$((n + 1))
    if [ -d "$BASE/$run" ]; then echo "[$n/${#plan[@]}] skip $run"; continue; fi
    echo "[$n/${#plan[@]}] === $run (rbps=$lim) ==="
    io_arg=""; [ "$lim" != "none" ] && io_arg="rbps:$lim"
    # need a non-empty IO path to trigger drop_caches even when uncapped:
    [ "$lim" = "none" ] && io_arg="rbps:max"   # sentinel: handled below
    if [ "$lim" = "none" ]; then
        # uncapped: drop caches but set no io.max. Pass MEM high:max to force
        # the drop path without an io limit.
        RUNS_DIR=$BASE bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" max t8_ioread.sh "$F_MB" high:max ""
    else
        RUNS_DIR=$BASE bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" max t8_ioread.sh "$F_MB" "" "rbps:$lim"
    fi
    echo "$run,t8_ioread.sh,$lim,$r,$(date -Is)" >> "$MANIFEST"
    sleep 10
done
echo "t8 campaign complete"
