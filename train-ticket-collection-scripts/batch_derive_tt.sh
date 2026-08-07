#!/bin/bash
# Batch L1 + L3 derive across ALL Train Ticket runs (the TT analogue of the Sock Shop 46-run
# batch). For each run: derive_kernel_l1.py (KPI parquet) then derive_kernel_l3.py (NL digest),
# with STRATATRACE_APP=trainticket so service_map uses the TT profile. Resumable (a run whose
# kernel_l1.parquet + kernel_l3.jsonl already exist is skipped). Concurrency pool (sliding window).
#
#   CONCURRENCY=3 ./batch_derive_tt.sh
#
# VM-only + long-running (~10-16 h for 49 TT runs; derivers gunzip each ~4.7 GB gz kernel CTF to
# TMPDIR then babeltrace-decode it). Launch detached via systemd-run (see progress-notes 04-08).
set -uo pipefail
STRATA_REPO="${STRATA_REPO:-$HOME/microservice-trace-dataset}"
export STRATATRACE_APP=trainticket
export PYTHONPATH="$STRATA_REPO:${PYTHONPATH:-}"
# gunzipped CTF temp lands here - route to the big data disk, NOT the smaller root /tmp.
export TMPDIR="${TMPDIR:-/mnt/data/tmp}"; mkdir -p "$TMPDIR"
L1="$STRATA_REPO/stratatrace/derive_kernel_l1.py"
L3="$STRATA_REPO/stratatrace/derive_kernel_l3.py"
LOG="$HOME/tt_derive.log"
CONCURRENCY="${CONCURRENCY:-3}"
TRACES_GLOB="${TRACES_GLOB:-/mnt/data/traces/*/tt_*/}"

derive_one() {
  local d="$1"; local rid; rid=$(basename "$d")
  [ -f "$d/meta/runinfo_end.txt" ] || { echo "SKIP $rid (incomplete bundle)"; return; }
  if [ -f "$d/kernel_l1.parquet" ] && [ -f "$d/kernel_l3.jsonl" ]; then echo "SKIP $rid (already derived)"; return; fi
  local t0; t0=$(date -u +%s)
  if python3 "$L1" "$d" --reader cli > "$d/derive_l1.log" 2>&1 \
     && python3 "$L3" "$d" > "$d/derive_l3.log" 2>&1; then
    echo "OK   $rid ($(( $(date -u +%s) - t0 ))s)"
  else
    echo "FAIL $rid (see $d/derive_l1.log / derive_l3.log)"
  fi
}

mapfile -t RUNS < <(ls -d $TRACES_GLOB 2>/dev/null)
echo "=== TT batch derive: ${#RUNS[@]} runs, concurrency $CONCURRENCY, TMPDIR=$TMPDIR ($(date -u)) ===" | tee "$LOG"
for d in "${RUNS[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do wait -n; done
  { derive_one "$d" >> "$LOG" 2>&1; } &
done
wait
echo "=== BATCH DONE $(date -u): ok=$(grep -c '^OK' "$LOG") skip=$(grep -c '^SKIP' "$LOG") fail=$(grep -c '^FAIL' "$LOG") ===" | tee -a "$LOG"
