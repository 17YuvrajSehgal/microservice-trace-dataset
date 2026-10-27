#!/bin/bash
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-index
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=02:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-index-%j.out
# Build the kernel-trace count index (+ line sample) for every run in the manifest.
# Pure babeltrace decode, no internet - so it belongs on a compute node (the API-calling
# eval stays on the login node). Trillium schedules whole 192-core nodes, so we take ONE
# node and run the builds in parallel on it with xargs -P, rather than an array of 76
# whole-node jobs. Resumable: build_ctf_index.py SKIPs a run whose index already exists.
set -uo pipefail

MANIFEST=${MANIFEST:-/scratch/yuvraj17/stratatrace/bp_eval/index-manifest.txt}
OUT=${OUT:-/scratch/yuvraj17/stratatrace/dataset/index-v2}
REPO=${REPO:-/scratch/yuvraj17/stratatrace/repo}
JOBS=${JOBS:-32}                 # concurrent decodes; IO-bound on scratch, not core-bound
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export TMPDIR="${SLURM_TMPDIR:-/tmp}/bt"; mkdir -p "$TMPDIR"
module load python/3.11 >/dev/null 2>&1 || true

mkdir -p "$OUT"
echo "node=$(hostname) jobs=$JOBS runs=$(wc -l < "$MANIFEST") out=$OUT"
"$BT2" --version | head -1

# one python per run; xargs feeds the manifest, -P fans out
xargs -P "$JOBS" -a "$MANIFEST" -I{} \
  python3 "$REPO/blueprints/lib/build_ctf_index.py" {} --out-root "$OUT" --with-lines

echo "built=$(ls "$OUT"/*.tsv.gz 2>/dev/null | wc -l) tsv.gz total in $OUT"
