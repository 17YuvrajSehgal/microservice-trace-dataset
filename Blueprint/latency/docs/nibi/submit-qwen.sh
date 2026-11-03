#!/bin/bash
# Qwen3.8-27B on ONE H100, 12 h (a 12 h request backfills into partly used nodes far sooner
# than a 24 h one; the agent runs are restart-safe, so a shorter server costs a resubmit, not work).
# No -p: Nibi rejects an explicit partition and routes by walltime + resources itself.
set -euo pipefail
BASE=${BASE:-/scratch/yuvraj17/c7-llm}
cd $BASE
sbatch -t 12:00:00 \
  --gpus-per-node=h100:1 --cpus-per-task=12 --mem=120G \
  --job-name=vllm-serve \
  --export=ALL,BASE=$BASE,MODEL_DIR=$BASE/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 --enable-prefix-caching" \
  $BASE/serve-llm.sbatch
