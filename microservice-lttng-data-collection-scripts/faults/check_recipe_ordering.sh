#!/bin/bash
# Does any recipe DISRUPT the system before it calls gt_begin?
#
# gt_begin stamps the start of the incident window, so everything before it counts as
# BASELINE. A recipe that applies its fault and then stamps puts the disruption inside the
# baseline - and a baseline that contains the fault is not a reference.
#
# This was true of ELEVEN recipes when the check was first written:
#   code_defect_lib.sh  restarted the container, slept 6s, then stamped. 28-80% retransmission
#                       in the baseline of all 25 code-defect runs.
#   anomaly_net.sh      applied netem across 16-44 container namespaces, then stamped. 5 of 16
#                       runs carry baseline retransmission up to 50%.
#   nine others         stamped after their docker run / docker update / nsenter / toxic_add.
#
# WHAT IT LOOKS AT, and every one of these rules came from a false result:
#   1. The `inject)` branch ONLY. Scanning whole files flagged disruptive lines inside FUNCTION
#      DEFINITIONS near the top, which belong to another branch. Three correct recipes were
#      reported broken.
#   2. Not plain variable assignments - STRESS_IMAGE=".../stress-ng:latest" is not a stressor.
#      But N=$(apply_each add ...) IS a call, so an assignment is only ignored when its
#      right-hand side has no command substitution. The first filter hid anomaly_net's netem
#      loop behind its own assignment.
#   3. Not prose - REMEDIATION="restore the quota via docker update" is documentation.
#   4. Wrapper functions are DISCOVERED, not listed. A hand-written list failed twice in ten
#      minutes: it missed anomaly_net's `apply_each`, then missed slow_db's `toxic_add`
#      because the list said `add_toxic`. A list you have to remember to update is not a check.
#
# Over-flagging is the right failure direction: a false alarm costs a minute, a contaminated
# baseline costs a campaign. Run this before any collection campaign.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

# Things that change the system directly.
DISRUPT='docker (run|restart|update|stop|kill|rm|exec)|tc qdisc (add|change)|nsenter|iptables|prlimit|stress-ng|toxiproxy|compose .*up|systemctl'

# Helpers that only READ state. Everything else defined in a recipe or in fault_lib.sh is
# treated as potentially disruptive.
SAFE='gt_begin|gt_end|resolve_container|compose_container|container_pid|stack_containers|limit_of|target_pid|resolver_ip|rule_args|ns|usage|require|_cd_compose|_cd_repo|compose_stack|fn_names|idle_fds|code_defect_is_armed|code_defect_require_image'

# A line may say it is deliberately before the stamp, with a reason. Used where the
# thing being started is not the fault - data_exfiltration brings up an idle sink so
# the sender has somewhere to send. Suppression is per line and has to carry a reason,
# so it cannot be used to silence the check wholesale.
OK_MARK='# ordering-ok:'

fn_names() {   # every function defined in <recipe> or in the shared library
    grep -hoE '^[[:space:]]*[a-z_][a-z0-9_]*[[:space:]]*\(\)' "$1" fault_lib.sh 2>/dev/null |
        tr -d ' ()' | sort -u | grep -vE "^($SAFE)$" | paste -sd'|' -
}

printf '%-28s %-10s %-12s %s\n' RECIPE gt_begin "1st disrupt" VERDICT
printf '%.0s-' {1..88}; echo
bad=0
checked=0
for f in *.sh; do
    case "$f" in
      fault_lib.sh|measure_targets.sh|build_workload_image.sh|check_recipe_ordering.sh|smoke_recipes.sh)
        continue ;;
    esac

    # The inject branch only, with real file line numbers kept.
    blk=$(awk 'BEGIN{on=0}
               /^[[:space:]]*inject\)/{on=1}
               on{print NR": "$0}
               on && /^[[:space:]]*;;[[:space:]]*$/{exit}' "$f")
    if [ -z "$blk" ]; then
        printf '%-28s %-10s %-12s %s\n' "$f" "-" "-" "no inject branch (library or helper)"
        continue
    fi

    gb=$(printf '%s\n' "$blk" | grep -E '^[0-9]+: [^#]*gt_begin' | head -1 | cut -d: -f1)
    if [ -z "$gb" ]; then
        printf '%-28s %-10s %-12s %s\n' "$f" "-" "-" "inject does not stamp (delegates to a lib)"
        continue
    fi

    wrap=$(fn_names "$f")
    pat="$DISRUPT"
    [ -n "$wrap" ] && pat="$DISRUPT|$wrap"
    d=$(printf '%s\n' "$blk" |
        grep -E "^[0-9]+: [^#]*($pat)" |
        grep -vE '^[0-9]+: [[:space:]]*[A-Za-z_][A-Za-z0-9_]*=[^$]*$' |
        grep -vE '^[0-9]+: [[:space:]]*(echo|printf)' |
        grep -vF "$OK_MARK" |
        head -1 | cut -d: -f1)
    checked=$((checked+1))
    if [ -z "$d" ]; then
        printf '%-28s %-10s %-12s %s\n' "$f" "$gb" "-" "ok (nothing disruptive in inject)"
    elif [ "$d" -lt "$gb" ]; then
        printf '%-28s %-10s %-12s %s\n' "$f" "$gb" "$d" "*** DISRUPTS BEFORE gt_begin ***"
        bad=$((bad+1))
    else
        printf '%-28s %-10s %-12s %s\n' "$f" "$gb" "$d" "ok"
    fi
done
echo
if [ "$bad" -gt 0 ]; then
    echo "$bad of $checked recipes disrupt the system before stamping the incident start."
    echo "Their baseline windows will contain part of the fault. Fix before collecting."
    exit 1
fi
echo "all $checked recipes stamp the incident start before disrupting anything."
