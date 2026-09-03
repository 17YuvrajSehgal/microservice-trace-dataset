#!/bin/bash
# Are the outputs reproducible now?
#
# The instability came from row order following Python's per-process string hashing, so the
# strong test is to FORCE two different hash seeds. Consecutive default runs might agree by
# luck; PYTHONHASHSEED=1 vs =2 guarantees different set/dict iteration order.
#
# Reads from the shared cache, so each run is ~30 s instead of ~200 s.
set -uo pipefail
REPO=/scratch/yuvraj17/stratatrace/repo
RUN=/scratch/yuvraj17/stratatrace/data/l0/sockshop/anomaly_cpu_aggressive_steady_r1
CTF=$RUN/ctf
GT=$RUN/ground_truth.json
V=/scratch/yuvraj17/stratatrace/results/repro
mkdir -p "$V"
export CTF_CACHE_DIR=/scratch/yuvraj17/stratatrace/results/verify/cache
cd "$REPO" || exit 1

check () {   # check <label> <script> [extra args...]
  local name="$1" script="$2"; shift 2
  PYTHONHASHSEED=1 python3 "$script" --ctf "$CTF" --gt "$GT" --out "$V/${name}_h1.json" \
      "$@" > "$V/${name}_h1.log" 2>&1
  PYTHONHASHSEED=2 python3 "$script" --ctf "$CTF" --gt "$GT" --out "$V/${name}_h2.json" \
      "$@" > "$V/${name}_h2.log" 2>&1
  if [ ! -s "$V/${name}_h1.json" ] || [ ! -s "$V/${name}_h2.json" ]; then
    echo "  $name: NO OUTPUT - see $V/${name}_h1.log"
    tail -3 "$V/${name}_h1.log" | sed 's/^/      /'
    return
  fi
  if diff -q "$V/${name}_h1.json" "$V/${name}_h2.json" > /dev/null; then
    echo "  $name: REPRODUCIBLE (byte-identical across hash seeds)"
  else
    echo "  $name: **STILL VARIES**"
    diff "$V/${name}_h1.json" "$V/${name}_h2.json" | head -10 | sed 's/^/      /'
  fi
}

echo "=== same trace, two different PYTHONHASHSEEDs ==="
check oncpu    blueprints/problems/cpu-contention-co-tenant/scripts/oncpu_share.py
check runq     blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py
check netloss  blueprints/problems/network-path-degradation/scripts/net_loss_signature.py
check flows    blueprints/lib/flow_activity.py
