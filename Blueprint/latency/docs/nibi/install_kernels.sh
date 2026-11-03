#!/bin/bash
# Trillium quirk 5 by hand (Nibi's login node has no GPU, so `vllm download-kernels` cannot run):
# the exact wheels vLLM 0.32.0 + flashinfer-python 0.7.0.post1 want, from FlashInfer's own index.
# The command lines are what `python -m flashinfer install-cubin-wheel --dry-run` prints.
B=${BASE:-/scratch/yuvraj17/c7-llm}; export PATH=$HOME/.local/bin:$PATH UV_CACHE_DIR=$B/cache/uv
PY=$B/vllm-venv/bin/python
exec > $B/logs/kernels.log 2>&1
echo "=== $(date)"
uv pip install --python $PY --upgrade --no-deps --index-url https://flashinfer.ai/whl "flashinfer-cubin==0.7.0.post1" && \
uv pip install --python $PY --upgrade --no-deps --index-url https://flashinfer.ai/whl/cu130/ "flashinfer-jit-cache==0.7.0.post1+cu130" "flashinfer-jit-cache-sm90a==0.7.0.post1+cu130"
echo "=== exit $? $(date)"
ls $B/vllm-venv/lib/python3.12/site-packages | grep -i flashinfer | grep -v dist-info | sort -u
ls -d $B/vllm-venv/lib/python3.12/site-packages/flashinfer_jit_cache_sm90a* >/dev/null 2>&1 && ls -d $B/vllm-venv/lib/python3.12/site-packages/flashinfer_cubin >/dev/null 2>&1 && touch $B/.done/kernels && echo "KERNELS OK"
