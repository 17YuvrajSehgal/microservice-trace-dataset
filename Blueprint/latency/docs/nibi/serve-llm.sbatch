#!/bin/bash
# Serve an open LLM with vLLM (OpenAI-compatible API, port 8000) on Nibi GPU nodes.
# Ported from Trillium's serve-llm.sbatch (2026-11-03). Nibi differences baked in:
#   - nodes are 8x H100 80GB, scheduled PER GPU: partitions gpubase_bygpu_b1..b5
#     (3h / 12h / 1d / 3d / 7d walltime); --mem is allowed (and wanted).
#   - account is def-naser2_gpu (not def-naser2).
#   - everything lives under $BASE (default /project/def-naser2/yuvraj17/c7-llm) because
#     /scratch is at quota; override with BASE=... if that changes.
#
# 1x H100, Qwen3.8-27B (fast per-GPU queue):
#   sbatch -p gpubase_bygpu_b3 -t 24:00:00 --gpus-per-node=h100:1 --cpus-per-task=12 --mem=120G \
#     --export=ALL,MODEL_DIR=$BASE/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 --enable-prefix-caching" \
#     serve-llm.sbatch
# 4x H100, GLM-5.3-Flash NVFP4 (TP=4):
#   sbatch -p gpubase_bygpu_b3 -t 24:00:00 --gpus-per-node=h100:4 --cpus-per-task=48 --mem=480G \
#     --export=ALL,MODEL_DIR=$BASE/models/GLM-5.3-Flash-NVFP4,NAME=glm-5.3-flash,TP=4,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser glm47 --reasoning-parser glm47 --enable-prefix-caching" \
#     serve-llm.sbatch
#SBATCH --account=def-naser2_gpu
#SBATCH --nodes=1
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=120G
#SBATCH --time=24:00:00
#SBATCH --job-name=vllm-serve

set -euo pipefail
BASE=${BASE:-/project/def-naser2/yuvraj17/c7-llm}
MODEL_DIR=${MODEL_DIR:?export MODEL_DIR=...}
NAME=${NAME:?export NAME=...}
TP=${TP:-1}
MAXLEN=${MAXLEN:-131072}
PORT=${PORT:-8000}
mkdir -p $BASE/logs
exec > $BASE/logs/serve-$SLURM_JOB_ID.out 2>&1

echo "node: $(hostname)  serving $NAME (TP=$TP) from $MODEL_DIR"
nvidia-smi -L

# compute nodes: assume no internet - everything comes from $BASE
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
CACHE=$BASE/cache
mkdir -p $CACHE/vllm $CACHE/hf $CACHE/triton $CACHE/inductor $CACHE/xdg
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

SERVE_ARGS=(serve "$MODEL_DIR"
    --served-model-name "$NAME"
    --tensor-parallel-size "$TP"
    --max-model-len "$MAXLEN"
    --max-num-seqs "${MAXSEQS:-32}"
    --gpu-memory-utilization 0.92
    --host 0.0.0.0 --port $PORT
    ${EXTRA_ARGS:-})
echo "stack: uv venv $BASE/vllm-venv"
$BASE/vllm-venv/bin/vllm "${SERVE_ARGS[@]}" > $BASE/logs/vllm-$SLURM_JOB_ID.log 2>&1 &
VLLM_PID=$!

# wait for the server (big models take minutes to load and warm up)
for i in $(seq 1 160); do
  if curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q "$NAME"; then
    echo "server up after ~$((i*15))s"; break
  fi
  kill -0 $VLLM_PID 2>/dev/null || { echo "vllm died; see vllm-$SLURM_JOB_ID.log"; exit 1; }
  sleep 15
done

# smoke test 1: one deterministic completion
curl -s "http://localhost:$PORT/v1/chat/completions" -H 'Content-Type: application/json' -d "{
  \"model\": \"$NAME\",
  \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: SERVING_OK\"}],
  \"max_tokens\": 10, \"temperature\": 0,
  \"chat_template_kwargs\": {\"enable_thinking\": false}
}" | tee $BASE/logs/smoke-$SLURM_JOB_ID.json
echo
# smoke test 2: a native tool call (the agent dies without this)
curl -s "http://localhost:$PORT/v1/chat/completions" -H 'Content-Type: application/json' -d "{
  \"model\": \"$NAME\", \"temperature\": 0, \"max_tokens\": 200,
  \"chat_template_kwargs\": {\"enable_thinking\": false},
  \"messages\": [{\"role\": \"user\", \"content\": \"What is the weather in Toronto? Use the tool.\"}],
  \"tools\": [{\"type\": \"function\", \"function\": {\"name\": \"get_weather\", \"description\": \"weather for a city\",
     \"parameters\": {\"type\": \"object\", \"properties\": {\"city\": {\"type\": \"string\"}}, \"required\": [\"city\"]}}}],
  \"tool_choice\": \"auto\"
}" | tee $BASE/logs/smoke-tool-$SLURM_JOB_ID.json
echo
echo "endpoint: http://$(hostname):$PORT/v1"
wait $VLLM_PID
