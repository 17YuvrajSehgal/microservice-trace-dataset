#!/bin/bash
# bridge.sh - make the Nibi vLLM server reachable from the Trillium login node.
#
# Nibi GPU node <-(ssh -L)- laptop WSL -(ssh -R)-> Trillium login node
#   localhost:8000 on the laptop  == the Nibi server
#   localhost:8000 on trillium    == the laptop's :8000 == the Nibi server
# So on Trillium: OPENAI_BASE_URL=http://localhost:8000/v1 (RCA_PROVIDER=openai, RCA_MODEL=<served name>).
#
# Run from WSL (both authenticated SSH sessions live there):  bash bridge.sh [start|stop|status]
# Both tunnels are started in the background with autossh-style retry loops; logs in ~/bridge-*.log.
set -u
BASE=${BASE:-/scratch/yuvraj17/c7-llm}
PORT=${PORT:-8000}
cmd=${1:-start}
case $cmd in
  start)
    NODE=$(ssh -o BatchMode=yes nibi "grep -h '^node: ' \$(ls -t $BASE/logs/serve-*.out 2>/dev/null | head -3) 2>/dev/null | head -1 | awk '{print \$2}'")
    [ -z "$NODE" ] && { echo "no running Nibi server found in $BASE/logs"; exit 1; }
    echo "nibi server node: $NODE"
    pkill -f "ssh .* -L $PORT:" 2>/dev/null; pkill -f "ssh .* -R $PORT:" 2>/dev/null
    nohup bash -c "while true; do ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes nibi -L $PORT:$NODE:$PORT -N; sleep 5; done" > ~/bridge-nibi.log 2>&1 &
    sleep 2
    nohup bash -c "while true; do ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes trillium -R $PORT:localhost:$PORT -N; sleep 5; done" > ~/bridge-trillium.log 2>&1 &
    sleep 3
    echo "laptop  -> nibi:   $(curl -s -m 5 http://localhost:$PORT/v1/models | head -c 120)"
    echo "trillium -> nibi:  $(ssh -o BatchMode=yes trillium "curl -s -m 5 http://localhost:$PORT/v1/models | head -c 120")"
    ;;
  stop)   pkill -f "ssh .* -L $PORT:"; pkill -f "ssh .* -R $PORT:"; pkill -f "while true; do ssh"; echo stopped ;;
  status) pgrep -af "ssh .* -[LR] $PORT:" || echo "no tunnels"; curl -s -m 5 http://localhost:$PORT/v1/models | head -c 200; echo ;;
  *) echo "usage: $0 start|stop|status"; exit 1 ;;
esac
