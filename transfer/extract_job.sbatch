#!/bin/bash
# Extract BOTH apps' small-modality working sets into /scratch. Trillium uses whole-node
# scheduling, so this job owns a full 192-core node — decompress every recipe in parallel.
# Submit:  sbatch transfer/extract_job.sbatch      (from the repo root on Trillium)
# Watch:   squeue --me    /    tail -f /scratch/yuvraj17/strata-extract-<jobid>.out
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-extract
#SBATCH --partition=debug
#SBATCH --nodes=1
#SBATCH --time=00:55:00
#SBATCH --output=/scratch/yuvraj17/strata-extract-%j.out
set -uo pipefail
cd /scratch/yuvraj17/microservice-trace-dataset
export RUNGLOB="${RUNGLOB:-*}"          # all runs; override at submit: sbatch --export=RUNGLOB='*_r1' ...
echo "== extract job start $(date) | RUNGLOB=$RUNGLOB =="
PAR=12 bash transfer/extract_working_set.sh trainticket
PAR=14 bash transfer/extract_working_set.sh sockshop
echo "== extract job done $(date) =="
du -sh /scratch/yuvraj17/agentic-runs/* 2>/dev/null
