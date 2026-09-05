#!/bin/bash
# Smoke-test the ten new fault recipes before they earn campaign runs.
#
# Same reasoning as the code-defect smoke test: a recipe that injects nothing produces a run
# labelled as a fault that never happened, and nothing downstream can tell. So each recipe has
# to demonstrate four things:
#
#   1. inject exits 0
#   2. ground truth is written, with an injection_start and no end yet
#   3. the fault is DEMONSTRABLY ACTIVE - checked against evidence the fault itself produces,
#      not merely "a container is running"
#   4. cleanup exits 0, closes the window, and leaves nothing behind
#
# Point 3 is per-fault on purpose. Every workload reports what it is doing, so the honest check
# is to read what it actually did rather than assume a running container means a working fault.
#
#   ./smoke_recipes.sh [recipe ...]      default: all ten
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STATE="${FAULT_STATE_DIR:-$HOME/fault-state}"
SETTLE="${SETTLE:-25}"      # seconds to let a workload produce evidence

RECIPES=("$@")
[[ ${#RECIPES[@]} -eq 0 ]] && RECIPES=(lock_contention priority_inversion deadlock \
                                       fd_exhaustion conn_pool_exhaustion \
                                       resource_abuse data_exfiltration fork_storm \
                                       dns_delay nagle_delayed_ack)

# What counts as PROOF that each fault is actually doing its job.
# container:<name>:<regex>  -> the container log must match the regex
# command:<shell>           -> the shell command must succeed
evidence_for() {
    case "$1" in
        lock_contention)      echo "container:lock-contention:acquisitions: [1-9]" ;;
        priority_inversion)   echo "container:priority-inversion:high-priority waits: [1-9]" ;;
        deadlock)             echo "container:deadlock:stuck pairs: [1-9]" ;;
        conn_pool_exhaustion) echo "container:conn-pool-exhaustion:holding [1-9][0-9]* connections" ;;
        resource_abuse)       echo "container:resource-abuse:hashes [1-9]" ;;
        data_exfiltration)    echo "container:data-exfiltration:sent [1-9]" ;;
        fork_storm)           echo "container:fork-storm:forked [1-9]" ;;
        nagle_delayed_ack)    echo "container:nagle-delayed-ack:nagle .*median" ;;
        # not a container: the proof is the rule being in the kernel
        dns_delay)            echo "command:sudo iptables -S OUTPUT | grep -q -- '--dport 53'" ;;
        # not a container either: the proof is descriptors held inside the target
        fd_exhaustion)        echo "command:docker exec \$(docker ps --format '{{.Names}}' | grep -m1 carts_1) sh -c 'ls /proc/*/fd 2>/dev/null | wc -l' | awk '{exit (\$1 > 500) ? 0 : 1}'" ;;
        *) echo "" ;;
    esac
}

leftovers_for() {   # what must be GONE after cleanup
    case "$1" in
        lock_contention)      echo "lock-contention" ;;
        priority_inversion)   echo "priority-inversion" ;;
        deadlock)             echo "deadlock" ;;
        conn_pool_exhaustion) echo "conn-pool-exhaustion" ;;
        resource_abuse)       echo "resource-abuse" ;;
        data_exfiltration)    echo "data-exfiltration" ;;
        fork_storm)           echo "fork-storm" ;;
        nagle_delayed_ack)    echo "nagle-delayed-ack" ;;
        *) echo "" ;;
    esac
}

pass=0; fail=0
echo "=============================================================="
echo " FAULT RECIPE SMOKE TEST  (settle ${SETTLE}s per recipe)"
echo "=============================================================="

for r in "${RECIPES[@]}"; do
    recipe="$SD/$r.sh"
    echo
    echo "--- $r ---"
    [[ -f "$recipe" ]] || { echo "  FAIL  recipe file missing"; fail=$((fail+1)); continue; }

    gt="$STATE/${r}.ground_truth.json"
    rm -f "$gt"

    # 1. inject
    if ! out=$(bash "$recipe" inject aggressive 2>&1); then
        echo "  FAIL  inject exited nonzero:"
        echo "$out" | tail -8 | sed 's/^/        /'
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi

    # 2. ground truth
    if [[ ! -f "$gt" ]]; then
        echo "  FAIL  no ground truth at $gt"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi
    if ! python3 -c "
import json,sys
d=json.load(open('$gt'))['fault']
sys.exit(0 if d.get('injection_start_utc') and d.get('injection_end_utc') is None else 1)" 2>/dev/null; then
        echo "  FAIL  ground truth has no open injection window"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi

    sleep "$SETTLE"

    # 3. is it actually doing anything?
    ev=$(evidence_for "$r")
    proved=0; detail=""
    if [[ "$ev" == container:* ]]; then
        cname="${ev#container:}"; pat="${cname#*:}"; cname="${cname%%:*}"
        log=$(docker logs "$cname" 2>&1 | tail -40)
        if echo "$log" | grep -qE "$pat"; then
            proved=1
            detail=$(echo "$log" | grep -E "$pat" | tail -1 | sed 's/^ *//')
        else
            detail=$(echo "$log" | tail -3 | tr '\n' ' ')
        fi
    elif [[ "$ev" == command:* ]]; then
        if eval "${ev#command:}" >/dev/null 2>&1; then proved=1; detail="check passed"; else detail="check failed"; fi
    fi

    if [[ "$proved" -eq 1 ]]; then
        echo "  active: $detail"
    else
        echo "  FAIL  no evidence the fault is doing anything"
        echo "        $detail"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi

    # 4. cleanup, window closed, nothing left behind
    if ! bash "$recipe" cleanup >/dev/null 2>&1; then
        echo "  FAIL  cleanup exited nonzero"; fail=$((fail+1)); continue
    fi
    if ! python3 -c "
import json,sys
d=json.load(open('$gt'))['fault']
sys.exit(0 if d.get('injection_end_utc') else 1)" 2>/dev/null; then
        echo "  FAIL  cleanup did not close the injection window"; fail=$((fail+1)); continue
    fi
    left=$(leftovers_for "$r")
    if [[ -n "$left" ]] && docker ps -a --format '{{.Names}}' | grep -qx "$left"; then
        echo "  FAIL  container '$left' still present after cleanup"; fail=$((fail+1)); continue
    fi
    if [[ "$r" == "dns_delay" ]] && sudo iptables -S OUTPUT 2>/dev/null | grep -q -- "--dport 53"; then
        echo "  FAIL  dns rule survived cleanup - it would poison every later run"
        fail=$((fail+1)); continue
    fi

    echo "  PASS  injects, proves itself, and cleans up completely"
    pass=$((pass+1))
done

echo
echo "=============================================================="
printf " RECIPE SMOKE: %d passed, %d failed\n" "$pass" "$fail"
[[ "$fail" -eq 0 ]] && echo " all ten recipes are campaign-ready" \
                    || echo " *** fix the failures before the campaign ***"
echo "=============================================================="
exit $(( fail > 0 ? 1 : 0 ))
