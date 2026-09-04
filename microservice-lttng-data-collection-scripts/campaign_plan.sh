#!/bin/bash
# Print the full v2 collection plan: every fault, its repeats, and which application it runs
# on. Generated from campaign_matrix.sh so the plan and the thing that actually runs cannot
# disagree - the two campaign drivers drifting apart is what made v1's run counts uneven.
#
#   ./campaign_plan.sh              the approved plan (all groups enabled)
#   ./campaign_plan.sh --current    only what has recipes TODAY
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SD/campaign_matrix.sh"

if [[ "${1:-}" != "--current" ]]; then
    # the approved plan: everything signed off on 4 Sept, pending recipes + pilot smoke runs
    CAMPAIGN_NEW_FAULTS=(lock_contention priority_inversion deadlock
                         fd_exhaustion conn_pool_exhaustion
                         resource_abuse data_exfiltration fork_storm
                         dns_delay nagle_delayed_ack)
    CAMPAIGN_CODE_BUGS=(code_lock_across_io code_n_plus_one code_event_loop_block
                        code_serial_awaits code_unbounded_cache)
    MODE="APPROVED PLAN (recipes still to be written + smoke-tested)"
else
    MODE="WHAT HAS RECIPES TODAY"
fi

echo "=================================================================="
echo " StrataTrace v2 collection plan - $MODE"
echo "=================================================================="

for app in sockshop trainticket; do
    build_matrix "$app" 2>/tmp/skips_$app
    echo
    echo "### $app - ${#MATRIX[@]} runs"
    printf '%s\n' "${MATRIX[@]}" \
      | awk '{print $1, $2, $3}' \
      | sort | uniq -c \
      | awk '{printf "  %-24s %-11s %-7s x%s\n", $2, $3, $4, $1}'
    if [[ -s /tmp/skips_$app ]]; then
        echo "  --- not run on this application:"
        sed 's/^\[matrix\] /  /' "/tmp/skips_$app"
    fi
done

echo
echo "### totals"
build_matrix sockshop 2>/dev/null; ss=${#MATRIX[@]}
build_matrix trainticket 2>/dev/null; tt=${#MATRIX[@]}
echo "  sockshop      $ss runs"
echo "  trainticket   $tt runs"
echo "  BOTH          $((ss + tt)) runs"
echo
echo "  at ~6 min/run: $(( (ss + tt) * 6 / 60 )) h of VM time"
echo "  windows: baseline ${BASELINE_S:-60}s / injection ${INJECTION_S:-120}s / recovery ${RECOVERY_S:-60}s"
rm -f /tmp/skips_sockshop /tmp/skips_trainticket
