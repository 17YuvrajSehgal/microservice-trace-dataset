#!/bin/bash
# Derive kernel L2 (wait-attribution) for BOTH apps so the two datasets are identical (L1+L2+L3).
# Heavy: decompresses each run's L0 CTF + runs babeltrace2 over the injection window per service.
# Whole-node (192 cores); PAR concurrent runs. Uses node-local $SLURM_TMPDIR for L0/gunzip temp.
# Submit:  sbatch transfer/derive_l2_job.sbatch
# Watch:   squeue --me   /   tail -f /scratch/yuvraj17/stratatrace/slurm-logs/strata-l2-<jobid>.out
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-l2
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=12:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-l2-%j.out
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo
export TZ=UTC                        # UTC window alignment (also forced in derive_kernel_l2.py)
module load python/3.11 >/dev/null 2>&1; module load arrow/19.0.1 >/dev/null 2>&1
source .venv/bin/activate
export STAGE="$SLURM_TMPDIR/stage"; export TMPDIR="$SLURM_TMPDIR/bt"; mkdir -p "$STAGE" "$TMPDIR"
export PAR="${PAR:-7}"               # concurrent runs per recipe (recipes hold <=7 runs); ~32GB shm each
export MAXSEC="${MAXSEC:-60}"        # attribution window (s) — first 60s of the steady 120s injection
echo "== L2 job start $(date) | PAR=$PAR MAXSEC=$MAXSEC | SLURM_TMPDIR=$SLURM_TMPDIR =="
df -h "$SLURM_TMPDIR" 2>/dev/null | tail -1
bash transfer/derive_l2_working_set.sh trainticket
bash transfer/derive_l2_working_set.sh sockshop
echo "== L2 job done $(date) =="
for app in trainticket sockshop; do
  echo "$app: $(ls /scratch/yuvraj17/stratatrace/data/agentic-runs/$app/*/*/kernel_l2.jsonl 2>/dev/null | wc -l) runs with L2"
done
