#!/bin/bash
# run_pilot.sh - the v4 pilot on the collection VM: every problem and language, 3 fault runs and 1
# healthy twin each. Run 1 of each pair is checked first; a pair whose run 1 is not "confirmed" is
# skipped (and listed). Ends by shutting the VM down.
#   setsid nohup bash v4/run_pilot.sh > ~/v4_pilot.log 2>&1 &
cd ~/microservice-trace-dataset && git pull -q --ff-only; git log --oneline -1 | cut -c1-70
V4=~/microservice-trace-dataset/v4
bash $V4/lib/setup_vm.sh | grep -v "^$" | tail -3
bash $V4/lib/build_all.sh | grep -v "^built"; echo "programs built: $(find $V4/build -mindepth 2 -maxdepth 2 -type d | wc -l)"
verdict() { python3 -c "import json; d=json.load(open('$1/verification.json')); print(d['verdict'], d.get('before_median'), '->', d.get('during_median'))" 2>/dev/null || echo "no_run"; }
for p in ${PROBLEMS:-deadlock lock_contention priority_inversion cpu_starvation slow_consumer io_stall}; do
  LANGS=$(sed -n 's/^LANGS="\(.*\)"/\1/p' $V4/problems/$p/problem.sh)
  for l in $LANGS; do
    A=~/archive/runs/v4_$p
    bash $V4/lib/collect_v4.sh $p $l fault 1 > ~/v4log_${p}_${l}_fault_1.log 2>&1
    v=$(verdict $A/v4_${p}_${l}_fault_r1); echo "$(date -u +%H:%M) $p/$l fault r1: $v"
    case "$v" in confirmed*) ;; *) echo "SKIP $p/$l: run 1 is $v"; continue ;; esac
    for r in 2 3; do
      bash $V4/lib/collect_v4.sh $p $l fault $r > ~/v4log_${p}_${l}_fault_$r.log 2>&1
      echo "$(date -u +%H:%M) $p/$l fault r$r: $(verdict $A/v4_${p}_${l}_fault_r$r)"
    done
    bash $V4/lib/collect_v4.sh $p $l healthy 1 > ~/v4log_${p}_${l}_healthy_1.log 2>&1
    echo "$(date -u +%H:%M) $p/$l healthy r1: $(verdict $A/v4_${p}_${l}_healthy_r1)"
  done
done
echo "PILOT END $(date -u +%H:%M)"
cut -d, -f6 ~/v4_manifest.csv | sort | uniq -c
du -sh ~/archive/runs/v4_* 2>/dev/null; df -h / | tail -1
echo "stopping the VM $(date -u +%H:%M)"; sleep 60; sudo shutdown -h now
