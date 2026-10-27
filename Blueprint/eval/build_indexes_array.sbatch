#!/bin/bash
#SBATCH --job-name=bp-index
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-index-%A_%a.out
# Build the kernel-trace count index (+ line sample) for one run per array task.
# No internet needed - pure babeltrace decode - which is exactly why this runs on compute
# nodes while the eval (API calls) stays on the login node.
#
# Usage:
#   1) make the manifest (login node, cheap):
#        Blueprint/eval/make_index_manifest.sh > /scratch/yuvraj17/stratatrace/bp_eval/index-manifest.txt
#   2) sbatch --array=0-$(( $(wc -l < .../index-manifest.txt) - 1 )) build_indexes_array.sbatch
#
# Resumable: a run whose index already exists is skipped (build_ctf_index.py SKIPs).
set -euo pipefail

MANIFEST=${MANIFEST:-/scratch/yuvraj17/stratatrace/bp_eval/index-manifest.txt}
OUT=${OUT:-/scratch/yuvraj17/stratatrace/dataset/index-v2}
REPO=${REPO:-/scratch/yuvraj17/stratatrace/repo}
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh

RUN_DIR=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$MANIFEST")
[ -n "$RUN_DIR" ] || { echo "no manifest line for task $SLURM_ARRAY_TASK_ID"; exit 1; }
echo "[task $SLURM_ARRAY_TASK_ID] $RUN_DIR"

python3 "$REPO/blueprints/lib/build_ctf_index.py" "$RUN_DIR" \
    --out-root "$OUT" --with-lines
