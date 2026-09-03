#!/bin/bash
# Do futex waits and interrupt time say anything about our 13 fault families?
#
# Both signals are ALREADY in every run - futex because we enable --syscall --all, softirq and
# hardirq because the profile enables irq_*/softirq_*. Neither has ever been read.
#
# We never injected a lock-contention fault, so the question is not "does futex find our
# faults". It is the negative control: **does futex stay quiet across all 13 families we do
# have?** If yes, a future rise in futex wait means lock contention and nothing else. Skipping
# exactly this check on packet loss (F17) is why that signal fired on a memory cap harder than
# on any network fault.
#
# Decoding needs no internet, so unlike the agent runs this belongs on a compute node.
#
#SBATCH --account=def-naser2
#SBATCH --job-name=bp-futexirq
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/bp-futexirq-%j.out
set -uo pipefail

REPO=/scratch/yuvraj17/stratatrace/repo
L0=/scratch/yuvraj17/stratatrace/data/l0
OUT=/scratch/yuvraj17/stratatrace/results/futexirq
PAR=${PAR:-10}          # concurrent runs; each is one babeltrace decode

mkdir -p "$OUT"
cd "$REPO" || exit 1

echo "== futex/irq probe start $(date -u +%FT%TZ) on $(hostname) =="
"$( [ -x /scratch/yuvraj17/stratatrace/tools/bt21.sh ] && echo /scratch/yuvraj17/stratatrace/tools/bt21.sh || echo true )" --version 2>&1 | head -1

one () {   # one <app> <run_id>
  local app="$1" run="$2"
  local ctf="$L0/$app/$run/ctf"
  local gt="$L0/$app/$run/ground_truth.json"
  local out="$OUT/${app}_${run}.json"
  [ -d "$ctf" ] || { echo "skip $run (no ctf)"; return; }
  [ -f "$gt" ]  || { echo "skip $run (no ground truth)"; return; }
  [ -s "$out" ] && { echo "skip $run (done)"; return; }
  python3 blueprints/lib/futex_irq_probe.py --ctf "$ctf" --gt "$gt" --out "$out" \
      > "$OUT/${app}_${run}.log" 2>&1 \
    && echo "ok   $app $run" || echo "FAIL $app $run"
}

# every Sock Shop run that has an expanded trace - all 13 families, so the negative control
# covers everything we can inject
mapfile -t RUNS < <(find "$L0/sockshop" -maxdepth 2 -name ctf -type d 2>/dev/null \
                    | sed 's#.*/sockshop/##; s#/ctf##' | sort)
echo "${#RUNS[@]} sockshop runs"

n=0
for r in "${RUNS[@]}"; do
  one sockshop "$r" &
  n=$((n+1))
  if [ $((n % PAR)) -eq 0 ]; then wait; fi
done
wait

echo
echo "== done $(date -u +%FT%TZ) =="
ls -1 "$OUT"/*.json 2>/dev/null | wc -l
python3 blueprints/lib/futexirq_report.py --dir "$OUT" --out "$OUT/report.json" || true
