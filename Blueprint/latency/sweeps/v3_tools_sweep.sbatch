#!/bin/bash
#SBATCH --account=def-naser2
#SBATCH --job-name=v3tools-sweep
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/v3tools-sweep-%j.out
# False-alarm check for the five tools of blueprints 25-32, on every run we have:
# v2 Sock Shop (170), v2 Train Ticket (134) and v3 Sock Shop (45).
#
#   inside_wait.py  (25 code_lock_contended, 30 db_table_lock)   fault slice against baseline slice
#   cpu_confine.py  (26 svc_cpuset)                              baseline, fault
#   new_errors.py   (27 disk_full, 28 port_exhaustion, 29 pid_limit)   baseline, fault
#   unanswered.py   (31 slow_client)                             fault against baseline
#   dev_delay.py    (32 net_bandwidth)                           fault against baseline
#
# One pair of slices per run feeds all five: 20 s that end 20 s before the injection
# (baseline) and 20 s that start 30 s into it (fault). Normal runs: "injection" = 100 s after
# the trace start, as in the earlier sweeps. The v3 kernel channels are gzipped on disk, so
# each v3 run is decompressed to a temporary copy first.
# Tool only, no API. Resumable: a run whose five outputs exist is skipped.
set -uo pipefail
D=/scratch/yuvraj17/stratatrace/data
N=/scratch/yuvraj17/stratatrace/work/dx_check/new
T=$N/25_code_lock_contended/tools
W=/scratch/yuvraj17/stratatrace/work/dx_check/sweep_v3tools
JOBS=${JOBS:-40}
JOBS_V3=${JOBS_V3:-12}          # each v3 run needs a 25-35 GB temporary copy
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export TMPDIR="${SLURM_TMPDIR:-/tmp}/bt"; mkdir -p "$TMPDIR" "$W/tmp" "$W/k"
module load python/3.11 >/dev/null 2>&1 || true
EV='net_dev_queue|sched_switch|sched_waking|sched_wakeup|syscall_exit_(connect|write|pwrite64|writev|pwritev|fallocate|fsync|fdatasync|ftruncate|openat|socket|accept4|accept|clone|clone3|fork|vfork|mmap|bind|sendto|sendmsg)'

one() {
  local R=$1
  local run; run=$(basename $R)
  [ -s $W/$run.iw ] && [ -s $W/$run.cc ] && [ -s $W/$run.ne ] && [ -s $W/$run.un ] && [ -s $W/$run.dd ] && { echo "skip $run"; return; }
  local K=$R/kernel tmpk=""
  if ls $R/kernel/kernel/*.gz >/dev/null 2>&1; then
    tmpk=$W/k/$run; rm -rf $tmpk; cp -a $R/kernel $tmpk && find $tmpk -name '*.gz' | xargs -r -P 4 -n 1 gzip -d
    K=$tmpk
  fi
  local CTF; CTF=$(dirname $(find $K -name metadata | head -1))
  local A
  A=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['fault']['injection_start_utc'])" $R/ground_truth.json 2>/dev/null)
  if [ -z "$A" ]; then
    local o; o=$(python3 $T/idx_summary.py "$CTF")
    A="$(echo "$o" | awk '/^date \(UTC\)/{print $4}')T$(echo "$o" | awk '/^trace start/{print substr($4,1,8)}')Z"
    A=$(date -u -d "$A + 100 seconds" +%Y-%m-%dT%H:%M:%SZ)
  fi
  local S=$W/tmp/$run; mkdir -p $S
  local day=${A:0:10}
  bash $T/extract_slice.sh "$CTF" $day $(date -u -d "$A - 40 seconds" +%H:%M:%S) 20 $S/b.txt "$EV" >> $S/ext.log 2>&1
  bash $T/extract_slice.sh "$CTF" $day $(date -u -d "$A + 30 seconds" +%H:%M:%S) 20 $S/f.txt "$EV" >> $S/ext.log 2>&1
  [ -n "$tmpk" ] && rm -rf $tmpk
  if [ -s $S/b.txt ] && [ -s $S/f.txt ]; then
    python3 $N/25_code_lock_contended/tools/inside_wait.py $S/f.txt 20 $S/b.txt > $W/$run.iw 2>&1
    python3 $N/26_svc_cpuset/tools/cpu_confine.py $S/b.txt $S/f.txt 20         > $W/$run.cc 2>&1
    python3 $N/27_disk_full/tools/new_errors.py $S/b.txt $S/f.txt 20           > $W/$run.ne 2>&1
    python3 $N/31_slow_client/unanswered.py $S/f.txt 20 $S/b.txt               > $W/$run.un 2>&1
    python3 $N/32_net_bandwidth/dev_delay.py $S/f.txt 20 $S/b.txt              > $W/$run.dd 2>&1
  else
    for x in iw cc ne un dd; do echo "SLICE FAILED ($(tail -1 $S/ext.log 2>/dev/null))" > $W/$run.$x; done
  fi
  rm -rf $S
  echo "done $run $(date +%H:%M:%S)"
}
export -f one; export D T W N EV
if [ -n "${PILOT:-}" ]; then one "$PILOT"; exit 0; fi       # one run, for a test on the login node
ls -d $D/stratatrace-v3/sockshop/*/*_r[0-9] > $W/todo_v3.txt
ls -d $D/stratatrace-v2/sockshop/*/*_r[0-9] $D/stratatrace-v2/trainticket/*/*_r[0-9] | grep -v -E "/(prometheus|_superseded)" > $W/todo_v2.txt
echo "node=$(hostname) v3 runs=$(wc -l < $W/todo_v3.txt) (jobs $JOBS_V3), v2 runs=$(wc -l < $W/todo_v2.txt) (jobs $JOBS), start $(date +%H:%M:%S)"
for t in $N/25_code_lock_contended/tools/inside_wait.py $N/26_svc_cpuset/tools/cpu_confine.py $N/27_disk_full/tools/new_errors.py $N/31_slow_client/unanswered.py $N/32_net_bandwidth/dev_delay.py; do
  echo "$(basename $t): $(python3 $t --selftest 2>&1 | tail -1), sha256 $(sha256sum $t | cut -c1-16)"
done
xargs -P "$JOBS_V3" -a $W/todo_v3.txt -I{} bash -c 'one {}'
echo "v3 part done $(date +%H:%M:%S)"
xargs -P "$JOBS" -a $W/todo_v2.txt -I{} bash -c 'one {}'
for x in iw cc ne un dd; do echo "$x=$(ls $W/*.$x | wc -l) failed=$(grep -l 'SLICE FAILED' $W/*.$x 2>/dev/null | wc -l)"; done
rm -rf $W/tmp $W/k
echo "SWEEP DONE $(date +%H:%M:%S)"
