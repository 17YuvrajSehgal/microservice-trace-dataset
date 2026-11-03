#!/bin/bash
# Serve an open LLM with vLLM on a Nibi MI300A node (AMD, 4x 128 GB unified memory per node),
# through the official ROCm vLLM container (docker://rocm/vllm:latest, pulled to $BASE/sifs).
# Why: the H100 queue estimate was ~42 h; MI300A nodes sat idle. Same OpenAI API on port 8000.
#   sbatch -t 12:00:00 --gpus-per-node=mi300a:1 --cpus-per-task=24 --mem=120G \
#     --export=ALL,BASE=$BASE,MODEL_DIR=$BASE/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 --enable-prefix-caching" \
#     serve-llm-rocm.sbatch
# GLM-5.3-Flash FP8 (330 GB) fits 4x MI300A (512 GB): --gpus-per-node=mi300a:4, TP=4.
#SBATCH --account=def-naser2_gpu
#SBATCH --nodes=1
#SBATCH --gpus-per-node=mi300a:1
#SBATCH --cpus-per-task=24
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --job-name=vllm-rocm

set -euo pipefail
BASE=${BASE:-/scratch/yuvraj17/c7-llm}
MODEL_DIR=${MODEL_DIR:?export MODEL_DIR=...}
NAME=${NAME:?export NAME=...}
TP=${TP:-1}
MAXLEN=${MAXLEN:-131072}
PORT=${PORT:-8000}
SIF=$BASE/sifs/vllm-rocm.sif
mkdir -p $BASE/logs
exec > $BASE/logs/serve-$SLURM_JOB_ID.out 2>&1

echo "node: $(hostname)  serving $NAME (TP=$TP) from $MODEL_DIR  [ROCm container]"
module load apptainer/1.2.4 2>/dev/null || module load apptainer
rocm-smi --showproductname 2>/dev/null | grep -i "card series" | head -4 || true

CACHE=$BASE/cache
mkdir -p $CACHE/vllm $CACHE/hf $CACHE/triton $CACHE/inductor $CACHE/xdg
export APPTAINERENV_HF_HUB_OFFLINE=1 APPTAINERENV_TRANSFORMERS_OFFLINE=1 APPTAINERENV_VLLM_NO_USAGE_STATS=1
export APPTAINERENV_VLLM_CACHE_ROOT=$CACHE/vllm APPTAINERENV_HF_HOME=$CACHE/hf APPTAINERENV_XDG_CACHE_HOME=$CACHE/xdg
export APPTAINERENV_TRITON_CACHE_DIR=$CACHE/triton APPTAINERENV_TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

SERVE_ARGS=(serve "$MODEL_DIR"
    --served-model-name "$NAME"
    --tensor-parallel-size "$TP"
    --max-model-len "$MAXLEN"
    --max-num-seqs "${MAXSEQS:-32}"
    --gpu-memory-utilization 0.90
    --host 0.0.0.0 --port $PORT
    ${EXTRA_ARGS:-})
apptainer exec --rocm --bind /scratch:/scratch "$SIF" vllm "${SERVE_ARGS[@]}" \
    > $BASE/logs/vllm-$SLURM_JOB_ID.log 2>&1 &
VLLM_PID=$!

for i in $(seq 1 160); do
  if curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q "$NAME"; then
    echo "server up after ~$((i*15))s"; break
  fi
  kill -0 $VLLM_PID 2>/dev/null || { echo "vllm died; see vllm-$SLURM_JOB_ID.log"; exit 1; }
  sleep 15
done

curl -s "http://localhost:$PORT/v1/chat/completions" -H 'Content-Type: application/json' -d "{
  \"model\": \"$NAME\",
  \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: SERVING_OK\"}],
  \"max_tokens\": 10, \"temperature\": 0,
  \"chat_template_kwargs\": {\"enable_thinking\": false}
}" | tee $BASE/logs/smoke-$SLURM_JOB_ID.json
echo
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
