#!/bin/bash
# GLM-5.3-Flash on Nibi. Two sizes:
#   nvfp4 (default): RedHatAI NVFP4, ~170 GB, 4x H100 (TP=4) - fits a partly used node, so it
#                    queues like a per-GPU job. NVFP4 on Hopper runs through vLLM's Marlin path.
#   fp8:             the official zai-org release, ~330 GB FP8, 8x H100 (TP=8, a whole node) -
#                    native FP8 on Hopper, best quality; waits for a full node to free.
#   bash submit-glm.sh [nvfp4|fp8]
set -euo pipefail
BASE=${BASE:-/scratch/yuvraj17/c7-llm}
KIND=${1:-nvfp4}
cd $BASE
case $KIND in
  nvfp4) sbatch -t 12:00:00 --gpus-per-node=h100:4 --cpus-per-task=48 --mem=480G \
           --job-name=vllm-serve \
           --export=ALL,BASE=$BASE,MODEL_DIR=$BASE/models/GLM-5.3-Flash-NVFP4,NAME=glm-5.3-flash,TP=4,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser glm47 --reasoning-parser glm47 --enable-prefix-caching" \
           $BASE/serve-llm.sbatch ;;
  fp8)   sbatch -t 12:00:00 --nodes=1 --gpus-per-node=h100:8 --cpus-per-task=112 --mem=1500G \
           --job-name=vllm-serve \
           --export=ALL,BASE=$BASE,MODEL_DIR=$BASE/models/GLM-5.3-Flash,NAME=glm-5.3-flash,TP=8,MAXLEN=131072,MAXSEQS=64,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser glm47 --reasoning-parser glm47 --enable-prefix-caching" \
           $BASE/serve-llm.sbatch ;;
  *) echo "usage: $0 [nvfp4|fp8]"; exit 1 ;;
esac
