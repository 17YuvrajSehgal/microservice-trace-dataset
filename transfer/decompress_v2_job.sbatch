#!/bin/bash
# Leave no .gz in the v2 working tree. Chained AFTER the extraction job so it cannot run against a
# half-populated tree:
#
#   sbatch --dependency=afterok:<extract_jobid> transfer/decompress_v2_job.sbatch
#
# Chaining rather than restarting the extraction as one combined job: the extraction was already
# RUNNING, and cancelling it to resubmit would have sent it back to the queue it had already
# waited in. A dependency costs nothing and starts the moment extraction succeeds.
#
# afterok, not afterany - if extraction fails, decompressing a partial tree would produce a
# working copy that looks finished and is not.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-v2-gunzip
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-v2-gunzip-%j.out
set -uo pipefail

REPO="${REPO:-/scratch/$USER/stratatrace/repo}"
mkdir -p "/scratch/$USER/stratatrace/slurm-logs"
cd "$REPO" || exit 1

echo "== gunzip start $(date) on $(hostname), $(nproc) cores =="
bash transfer/decompress_v2_tree.sh --check
echo
PAR="${PAR:-64}" bash transfer/decompress_v2_tree.sh
rc=$?
echo
bash transfer/decompress_v2_tree.sh --verify
echo "== gunzip done $(date), rc=$rc =="
df -h /scratch 2>/dev/null | tail -1
exit "$rc"
