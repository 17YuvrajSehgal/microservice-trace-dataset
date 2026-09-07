#!/bin/bash
# Extract the whole v2 release into a working tree on /scratch. Trillium uses whole-node
# scheduling, so this job owns all 192 cores - decompress many archives at once.
#
#   sbatch transfer/extract_v2_job.sbatch          # from the repo root on Trillium
#   squeue --me
#   tail -f /scratch/yuvraj17/stratatrace/slurm-logs/strata-v2-extract-<jobid>.out
#
# NOT the debug partition and not 55 minutes: that sizing was for v1's 109 runs. v2 is 303 runs
# and 778 GB compressed, expanding to ~1.18 TB across ~831,000 files.
#
# Safe to resubmit. Each finished archive drops a marker, so a job that hits the wall clock picks
# up where it stopped instead of redoing 778 GB.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-v2-extract
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-v2-extract-%j.out
set -uo pipefail

REPO="${REPO:-/scratch/$USER/stratatrace/repo}"
mkdir -p "/scratch/$USER/stratatrace/slurm-logs"
cd "$REPO" || exit 1

echo "== v2 extract start $(date) on $(hostname), $(nproc) cores =="
PAR="${PAR:-16}" bash transfer/extract_v2_full.sh
rc=$?
echo "== v2 extract done $(date), rc=$rc =="
df -h /scratch 2>/dev/null | tail -1
exit "$rc"
