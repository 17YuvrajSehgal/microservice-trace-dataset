#!/bin/bash
# Laptop tunnel to the running vLLM server on Nibi (one hop: nibi login -> GPU node).
# Run from WSL (where the authenticated nibi SSH session lives):
#   bash tunnel.sh            # then: curl http://localhost:8000/v1/models
set -e
BASE=${BASE:-/project/def-naser2/yuvraj17/c7-llm}
NODE=$(ssh nibi "grep -h '^node: ' \$(ls -t $BASE/logs/serve-*.out | head -3) 2>/dev/null | head -1 | awk '{print \$2}'")
[ -z "$NODE" ] && { echo "no running server found in recent logs"; exit 1; }
echo "tunneling localhost:8000 -> $NODE:8000 (Ctrl-C to stop)"
ssh nibi -L 8000:$NODE:8000 -N
