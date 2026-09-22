#!/bin/bash
#SBATCH --job-name=ctfindex
#SBATCH --nodes=1
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/ctfindex_%j.out
#
# Build every missing kernel count index, all on ONE node, in parallel.
#
# NOT a job array. Trillium schedules by whole 192-core node, so an array of fifteen tasks
# would take fifteen whole nodes to run fifteen single-threaded babeltrace decodes - 2,880
# cores to use 15. One node runs all of them at once and finishes in the time of the slowest.
# --mem is not accepted here either: every node has the same 745 GiB and a job gets all of it.
#
# Compute node rather than login: indexing only READS files, so the compute-node egress block
# does not matter, and one decode is ~9 minutes of solid CPU. The agent runs stay on the login
# node because those do need the Azure API.
#
#   sbatch transfer/build_indexes_array.sbatch [todo-file]

set -u
S=/scratch/yuvraj17/stratatrace
TODO="${1:-$S/results/index_todo.txt}"
PAR="${PAR:-16}"

echo "node $(hostname)   start $(date -u +%H:%M:%S)"
echo "todo: $TODO  ($(wc -l < "$TODO") runs)   parallel: $PAR"

# bt21.sh must resolve to babeltrace 2.1.2. 2.0.4 cannot read these traces at all, and the
# wrapper falls back to it silently if its paths go stale - so check rather than assume.
"$S/tools/bt21.sh" --version | head -1

grep -v '^[[:space:]]*$' "$TODO" | xargs -P "$PAR" -I{} \
  "$HOME/q2venv/bin/python" -u "$S/repo/blueprints/lib/build_ctf_index.py" {}
rc=$?

echo "end $(date -u +%H:%M:%S)  rc=$rc"
echo "indexes now: $(ls "$S/dataset/index"/*.tsv.gz 2>/dev/null | wc -l)"
exit $rc
