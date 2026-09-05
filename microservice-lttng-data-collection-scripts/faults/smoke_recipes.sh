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

# ---- proof helpers ---------------------------------------------------------------------------
# These are FUNCTIONS, not pipelines, on purpose.
#
# `cmd | grep -q` makes grep exit at the first match, which sends SIGPIPE to cmd, and with
# `set -o pipefail` the whole check then reports failure. That is exactly how the first
# fd_exhaustion check failed while the fault was working perfectly - the limit really was 64.
# dns_delay survived the same shape only by luck: iptables writes its whole output in one go
# before grep can exit. Capture first, match second, and neither depends on timing.
dns_rule_present() {
    local out; out=$(sudo iptables -S OUTPUT 2>/dev/null)
    [[ "$out" == *"--dport 53"* ]]
}

# Not a fixed number any more. The recipe now sets the limit from what the service actually
# uses, so it lands on whatever idle+headroom comes to - 29 on Sock Shop's front-end, something
# larger on a JVM. What makes it a fault is that it is far below the stock 524288, so that is
# what to test.
fd_limit_low() {
    local out lim
    out=$(bash "$SD/fd_exhaustion.sh" status 2>/dev/null)
    lim="${out#*limit: }"; lim="${lim%%$'
'*}"
    [[ "$lim" =~ ^[0-9]+$ && "$lim" -lt 4096 ]]
}

# The limit on its own is NOT proof. A ceiling the service never reaches is a fault that never
# happened - the same trap as a code defect that builds but does nothing. The recipe knows how
# to prove itself, so ask it: it drives load and reports the peak descriptor count against the
# limit. In a campaign run the load generator supplies the traffic instead.
fd_proof() {
    fd_limit_low || { echo "descriptor limit was not applied"; return 1; }
    bash "$SD/fd_exhaustion.sh" prove
}

# What counts as PROOF that each fault is actually doing its job.
# container:<name>:<regex>  -> the container log must match the regex
# command:<shell>           -> the shell command must succeed
evidence_for() {
    case "$1" in
        lock_contention)      echo "container:lock-contention:acquisitions: [1-9]" ;;
        priority_inversion)   echo "container:priority-inversion:high-priority waits: [1-9]" ;;
        deadlock)             echo "container:deadlock:stuck pairs: [1-9]" ;;
        # NOT "holding N connections" - that was the workload's own belief, and it was wrong.
        # The first version held pre-auth sockets that MySQL threw away; it reported holding 400
        # while the server reported Threads_connected=3. The evidence has to come from the thing
        # being attacked, so match on the server's own SHOW STATUS reading.
        conn_pool_exhaustion) echo "container:conn-pool-exhaustion:server Threads_connected=[1-9][0-9]" ;;
        resource_abuse)       echo "container:resource-abuse:hashes [1-9]" ;;
        data_exfiltration)    echo "container:data-exfiltration:sent [1-9]" ;;
        fork_storm)           echo "container:fork-storm:forked [1-9]" ;;
        nagle_delayed_ack)    echo "container:nagle-delayed-ack:nagle .*median" ;;
        # not a container: the proof is the rule being in the kernel
        dns_delay)            echo "command:dns_rule_present" ;;
        # not a container either: the proof is the SERVICE's own limit plus a service that
        # actually runs out of descriptors. RLIMIT_NOFILE is per process, so nothing an
        # external process does could ever demonstrate this fault.
        fd_exhaustion)        echo "command:fd_proof" ;;
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
APP="${STRATA_APP:-sockshop}"
echo "=============================================================="
echo " FAULT RECIPE SMOKE TEST  -  app: $APP  (settle ${SETTLE}s per recipe)"
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
        # keep the output: "check failed" told us nothing when fd_exhaustion failed, and the
        # real reason was in the line we were discarding.
        if detail=$(eval "${ev#command:}" 2>&1); then proved=1; fi
        detail="${detail:-(no output)}"
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
    if [[ "$r" == "dns_delay" ]] && dns_rule_present; then
        echo "  FAIL  dns rule survived cleanup - it would poison every later run"
        fail=$((fail+1)); continue
    fi
    # a descriptor limit left in place would quietly cap the service for every later run
    if [[ "$r" == "fd_exhaustion" ]] && fd_limit_low; then
        echo "  FAIL  the low descriptor limit survived cleanup"
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
