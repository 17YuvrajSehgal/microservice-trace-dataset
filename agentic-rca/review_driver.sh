#!/bin/bash
# Review-response experiments (answers.md items 3, 6, 8). Login-node, resumable:
# each output file is written once and skipped if present.
set -uo pipefail
cd /scratch/yuvraj17/microservice-trace-dataset || exit 1
source transfer/env.sh >/dev/null 2>&1
set -a; source .env; set +a
cd agentic-rca || exit 1
R=results/review; T=transcripts/review
mkdir -p "$R" "$T"

step () {  # step <out.json> <args...>
  local out="$1"; shift
  if [ -s "$R/$out" ]; then echo "SKIP $out (exists)"; return 0; fi
  echo "RUN  $out :: $*"
  if python evaluate.py "$@" --out "$R/$out" --transcripts "$T" >> "$R/${out%.json}.log" 2>&1; then
    echo "OK   $out"
  else
    echo "FAIL $out (see $R/${out%.json}.log)"
  fi
}

# --- item 3: model-only control (no tools), both apps, one incident per family -----------
step llmonly_ss.json  --app sockshop    --per-family 1 --method llmonly --grid full
step llmonly_tt.json  --app trainticket --per-family 1 --method llmonly --grid full
# cruder lower bound: raw survey dump instead of the briefing
step llmraw_ss.json   --app sockshop    --per-family 1 --method llmonly_raw --grid full
step llmraw_tt.json   --app trainticket --per-family 1 --method llmonly_raw --grid full

# --- item 8: ranked answers from the full agent (same v4-s0b config + rank list) ---------
step ranked_ss.json   --app sockshop    --per-family 1 --method agent --grid full --brief --rank-k 5
step ranked_tt.json   --app trainticket --per-family 1 --method agent --grid full --brief --rank-k 5
# ranked answers for the model-only control too, so the comparison is like-for-like
step ranked_llmonly_ss.json --app sockshop    --per-family 1 --method llmonly --grid full --rank-k 5
step ranked_llmonly_tt.json --app trainticket --per-family 1 --method llmonly --grid full --rank-k 5

echo "== review driver done $(date -u +%FT%TZ) =="
ls -la "$R"/*.json 2>/dev/null | awk '{print "   ", $5, $9}'
