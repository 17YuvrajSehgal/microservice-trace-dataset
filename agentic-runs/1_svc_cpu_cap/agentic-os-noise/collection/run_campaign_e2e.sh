#!/bin/bash
# Problem #3 (Mahsa's review): the REAL coding task (edit code + run tests)
# under memory and disk limits, reporting total completion time + task
# success. CPU-cap and unlimited baselines come from Problem 1 (reused in
# analysis). Agent coding-task memory peak is ~340 MiB, so memory.max is
# swept around it to catch the slowdown->OOM transition.
#   AGENT=claude|codex TASK=t3_implement.sh RUNS_DIR=~/runs_e2e_cl ./run_campaign_e2e.sh [reps]
set -u
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPS=${1:-3}
TASK=${TASK:-t3_implement.sh}
BASE=${RUNS_DIR:-$HOME/runs_e2e}
MEM=${MEM:-"512M 384M 320M 256M 192M 128M 96M"}
IO=${IO:-"52428800 20971520"}       # 50, 20 MB/s
mkdir -p "$BASE"
MAN=$BASE/manifest.csv
[ -f "$MAN" ] || echo "run,task,agent,limit_type,limit,rep,finished_at" > "$MAN"

run_one() {   # name  limit_type  mem_arg  io_arg  rep
    local run=$1 type=$2 mem=$3 io=$4 rep=$5
    [ -d "$BASE/$run" ] && { echo "  skip $run (exists)"; return; }
    RUNS_DIR=$BASE bash "$SCRIPT_DIR/collect_agent_run.sh" "$run" max "$TASK" "" "$mem" "$io" >/dev/null 2>&1
    echo "$run,$TASK,${AGENT:-claude},$type,${mem}${io},$rep,$(date -Is)" >> "$MAN"
    local g=$BASE/$run/meta/ground_truth.json
    echo "  $run exit=$(grep -oE '\"agent_exit\": [0-9]+' "$g"|grep -oE '[0-9]+') check=$(grep -oE '\"task_check_exit\": [0-9]+' "$g"|grep -oE '[0-9]+')"
}

echo "=== baseline (unlimited) ==="
for r in $(seq 1 "$REPS"); do run_one "e2e_unltd_r$r" unlimited high:max "" "$r"; done
echo "=== memory.max sweep (agent peak ~340 MiB) ==="
for m in $MEM; do for r in $(seq 1 "$REPS"); do run_one "e2e_mem${m}_r$r" memory "max:$m" "" "$r"; done; done
echo "=== io.max sweep ==="
for io in $IO; do mb=$((io/1048576)); for r in $(seq 1 "$REPS"); do run_one "e2e_io${mb}M_r$r" disk "" "rbps:$io" "$r"; done; done
echo "=== E2E COMPLETE ==="
