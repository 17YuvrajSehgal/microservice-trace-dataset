#!/bin/bash
# Every method, same 12 incidents, same evidence. Resumable: existing outputs are skipped.
set -uo pipefail
cd /scratch/yuvraj17/stratatrace/repo || exit 1
source transfer/env.sh >/dev/null 2>&1
set -a; source .env; set +a
cd agentic-rca || exit 1

C=/scratch/yuvraj17/stratatrace/results/comparison
PACKS=/scratch/yuvraj17/stratatrace/data/packs/evidence_packs
mkdir -p "$C/blueprint" "$C/transcripts"
FAMS=noisy_neighbor,slow_db

# --- arm 1: blueprint rules over the shared pack. No model, no API cost. -----------------
echo "== blueprint arm =="
for P in "$PACKS"/*.json; do
  R=$(basename "$P" .json)
  [ -s "$C/blueprint/$R.json" ] && continue
  python ../blueprints/lib/blueprint_decide.py --pack "$P" --out "$C/blueprint/$R.json"
done

step () {  # step <name> <args...>
  [ -s "$C/$1.json" ] && { echo "SKIP $1"; return 0; }
  echo "RUN  $1"
  local n="$1"; shift
  python evaluate.py --app sockshop --families "$FAMS" --grid full \
      --out "$C/$n.json" --transcripts "$C/transcripts/$n" "$@" >> "$C/$n.log" 2>&1 \
      && echo "OK   $n" || echo "FAIL $n"
}

# --- arms 2-4: LLM, with and without the same kernel evidence ---------------------------
step agent_l0    --method agent   --brief --l0-pack-dir "$PACKS"
step agent_nol0  --method agent   --brief
step llmonly_l0  --method llmonly --l0-pack-dir "$PACKS"

# --- arms 5-6: published non-LLM methods (cannot consume kernel data) --------------------
step stat        --method stat
step mmbaro      --method mmbaro

echo "== comparison runs done $(date -u +%FT%TZ) =="
