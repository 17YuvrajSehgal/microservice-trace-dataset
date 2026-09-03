#!/bin/bash
# Review-response experiments (answers.md items 3, 6, 8). Login-node, resumable.
# NOTE: every step below uses grid=full, so the transcript filename (<app>/<run>/full.json)
# is the SAME for all of them — each step therefore gets its OWN transcripts dir, or later
# steps silently overwrite earlier ones and most diagnoses become unauditable.
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo || exit 1
source transfer/env.sh >/dev/null 2>&1
set -a; source .env; set +a
cd agentic-rca || exit 1
R=results/review
mkdir -p "$R"

step () {  # step <name> <args...>
  local name="$1"; shift
  local out="$R/$name.json"
  if [ -s "$out" ]; then echo "SKIP $name (exists)"; return 0; fi
  echo "RUN  $name :: $*"
  if python evaluate.py "$@" --out "$out" --transcripts "transcripts/review/$name" >> "$R/$name.log" 2>&1; then
    echo "OK   $name"
  else
    echo "FAIL $name (see $R/$name.log)"
  fi
}

# --- item 3: model-only control (no tools) ------------------------------------------------
step llmonly_ss  --app sockshop    --per-family 1 --method llmonly --grid full
step llmonly_tt  --app trainticket --per-family 1 --method llmonly --grid full
step llmraw_ss   --app sockshop    --per-family 1 --method llmonly_raw --grid full
step llmraw_tt   --app trainticket --per-family 1 --method llmonly_raw --grid full

# --- item 8: ranked answers ---------------------------------------------------------------
step ranked_ss   --app sockshop    --per-family 1 --method agent --grid full --brief --rank-k 5
step ranked_tt   --app trainticket --per-family 1 --method agent --grid full --brief --rank-k 5
step ranked_llmonly_ss --app sockshop    --per-family 1 --method llmonly --grid full --rank-k 5
step ranked_llmonly_tt --app trainticket --per-family 1 --method llmonly --grid full --rank-k 5

# --- reference: the frozen agent config, same 23 incidents, single verdict ----------------
step agent_ref_ss --app sockshop    --per-family 1 --method agent --grid full --brief
step agent_ref_tt --app trainticket --per-family 1 --method agent --grid full --brief

echo "== review driver done $(date -u +%FT%TZ) =="
