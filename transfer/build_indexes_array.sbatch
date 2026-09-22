#!/bin/bash
#SBATCH --job-name=ctfindex
#SBATCH --array=1-15
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:45:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/ctfindex_%A_%a.out
#
# Build one kernel count index per run, one run per array task.
#
# Compute nodes, not the login node. Indexing only READS files - no API calls - so the
# compute-node egress block does not matter here, and one full babeltrace decode is ~9 minutes
# of solid CPU. Fifteen of those on a shared login node would be antisocial; as an array they
# finish in the time of the slowest one.
#
# The agent runs still go on the login node, because those DO need the Azure API.
#
#   sbatch --array=1-$(wc -l < $TODO) transfer/build_indexes_array.sbatch $TODO

set -u
S=/scratch/yuvraj17/stratatrace
TODO="${1:-$S/results/index_todo.txt}"

RUN_DIR=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$TODO")
if [ -z "$RUN_DIR" ]; then
  echo "no run for array index $SLURM_ARRAY_TASK_ID in $TODO"
  exit 0
fi

echo "task $SLURM_ARRAY_TASK_ID  ->  $RUN_DIR"
echo "host $(hostname)  start $(date -u +%H:%M:%S)"

# bt21.sh must resolve to babeltrace 2.1.2. 2.0.4 cannot read these traces at all, and the
# wrapper falls back to it silently if its paths go stale - so check rather than assume.
"$S/tools/bt21.sh" --version | head -1

"$HOME/q2venv/bin/python" -u "$S/repo/blueprints/lib/build_ctf_index.py" "$RUN_DIR"
rc=$?
echo "end $(date -u +%H:%M:%S)  rc=$rc"
exit $rc
