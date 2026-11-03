#!/bin/bash
# One-time staging for vLLM serving on Nibi (login node, has internet). Idempotent: every step
# leaves a marker in $BASE/.done/ and is skipped next time. Run under nohup; log in $BASE/logs/setup.log.
#   nohup bash setup_nibi.sh > /dev/null 2>&1 &
set -uo pipefail
BASE=${BASE:-/scratch/yuvraj17/c7-llm}
VLLM_VERSION=${VLLM_VERSION:-0.32.0}      # same build as Trillium (parsers qwen3_xml / glm47 verified there)
MODELS=${MODELS:-"Qwen/Qwen3.8-27B RedHatAI/GLM-5.3-Flash-NVFP4"}   # add zai-org/GLM-5.3-Flash (FP8, ~330 GB) for the 8-GPU option
mkdir -p $BASE/logs $BASE/.done $BASE/models $BASE/cache
exec >> $BASE/logs/setup.log 2>&1
echo "=== setup start $(date)  BASE=$BASE"
export PATH=$HOME/.local/bin:$PATH
export UV_CACHE_DIR=$BASE/cache/uv      # the standalone CPython is already in ~/.local/share/uv (home is mounted on Nibi compute nodes)
export HF_HOME=$BASE/cache/hf HF_HUB_ENABLE_HF_TRANSFER=1
step() { [ -f $BASE/.done/$1 ] && { echo "skip $1"; return 1; }; echo "--- $1 $(date +%T)"; return 0; }
ok() { touch $BASE/.done/$1; echo "    ok $1 $(date +%T)"; }

# 1. standalone CPython (the Alliance wheelhouse hijacks pip install vllm; uv sidesteps it)
if step python; then uv python install 3.12 && ok python; fi
# 2. venv + vLLM
if step venv; then uv venv --python 3.12 $BASE/vllm-venv && ok venv; fi
if step vllm; then
  uv pip install --python $BASE/vllm-venv/bin/python "vllm==$VLLM_VERSION" "huggingface_hub[cli,hf_transfer]" \
    && $BASE/vllm-venv/bin/python -c "import vllm, sys; print('vllm', vllm.__version__)" && ok vllm
fi
# 3. version-matched flashinfer kernels (Trillium quirk 5: the PyPI cubin lags and kills the engine)
if step kernels; then
  (cd $BASE && $BASE/vllm-venv/bin/vllm download-kernels) && ok kernels || echo "    download-kernels failed (non-fatal: vLLM falls back to JIT at first start)"
fi
# 4. models
for m in $MODELS; do
  d=$BASE/models/$(basename $m)
  if step "model-$(basename $m)"; then
    $BASE/vllm-venv/bin/hf download "$m" --local-dir "$d" && du -sh "$d" && ok "model-$(basename $m)"
  fi
done
echo "=== setup end $(date)"; ls $BASE/.done
