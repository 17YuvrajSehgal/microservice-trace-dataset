#!/bin/bash
# Find out which Prometheus metrics ACTUALLY move for each new fault.
#
# WHY THIS EXISTS
# ---------------
# verification_targets.json covers the 12 original families only. The ten new fault families and
# the five code defects have no entry, so verify_injection had nothing to check for 125 of the
# campaign's runs.
#
# The tempting fix is to write plausible PromQL from each fault's mechanism. That would be
# worse than leaving it empty: it would LOOK like verification while confirming nothing, which
# is exactly the mistake conn_pool_exhaustion made when its check read the injector's own log.
#
# So: inject each fault with load running, sample a panel of candidate metrics before and
# during, and print the measured ratio. Only what actually moves earns a place in the targets
# file, and the numbers there come from this run rather than from reasoning.
#
#   bash faults/measure_targets.sh [fault ...]        default: the ten new families
#   env: PROMETHEUS (http://localhost:9090) HOLD_S (60) STRATA_APP (sockshop)
set -uo pipefail
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROM="${PROMETHEUS:-http://localhost:9090}"
HOLD_S="${HOLD_S:-60}"
# Same fallback chain as fault_lib.sh - this script does not source it. The TT driver exports
# STRATATRACE_APP and TRACE_APP, not STRATA_APP.
APP="${STRATA_APP:-${STRATATRACE_APP:-${TRACE_APP:-sockshop}}}"

# Container name patterns differ per app; everything else is the same.
if [[ "$APP" == "trainticket" ]]; then
    FRONT='.*ts-gateway-service_1$'; DB='^mysql$'
else
    FRONT='.*front-end_1$';          DB='.*catalogue-db_1$'
fi

# Candidate panels. Deliberately WIDER than what will be registered - the point is to find out
# which of these move, not to confirm a guess. A candidate that does not move is a result too:
# it says the fault has no signature in that modality, which is a study claim, not a failure.
candidates_for() {
    case "$1" in
      lock_contention)      echo "cpu:rate(container_cpu_usage_seconds_total{name=\"lock-contention\"}[1m])
threads:container_threads{name=\"lock-contention\"}" ;;
      priority_inversion)   echo "cpu:rate(container_cpu_usage_seconds_total{name=\"priority-inversion\"}[1m])" ;;
      deadlock)             echo "cpu:rate(container_cpu_usage_seconds_total{name=\"deadlock\"}[1m])
threads:container_threads{name=\"deadlock\"}" ;;
      fd_exhaustion)        echo "front_fds:container_file_descriptors{name=~\"$FRONT\"}
front_cpu:rate(container_cpu_usage_seconds_total{name=~\"$FRONT\"}[1m])" ;;
      conn_pool_exhaustion) echo "db_fds:container_file_descriptors{name=~\"$DB\"}
db_socks:container_sockets{name=~\"$DB\"}
db_cpu:rate(container_cpu_usage_seconds_total{name=~\"$DB\"}[1m])" ;;
      resource_abuse)       echo "cpu:rate(container_cpu_usage_seconds_total{name=\"resource-abuse\"}[1m])
tx:rate(container_network_transmit_bytes_total{name=\"resource-abuse\"}[1m])" ;;
      data_exfiltration)    echo "tx:rate(container_network_transmit_bytes_total{name=\"data-exfiltration\"}[1m])
sink_rx:rate(container_network_receive_bytes_total{name=\"data-exfiltration-sink\"}[1m])
host_tx:rate(node_network_transmit_bytes_total{device!=\"lo\"}[1m])" ;;
      # host_forks is 14.25x on Sock Shop and 1.05x on Train Ticket - TT already forks ~112/s
      # from 40 JVMs and Nacos health checks, so the storm is lost in the noise. The
      # per-container counters are immune to that, which is the argument for enabling them.
      fork_storm)           echo "procs:container_processes{name=\"fork-storm\"}
threads:container_threads{name=\"fork-storm\"}
host_forks:rate(node_forks_total[1m])" ;;
      # These were written when the rule lived in the HOST's OUTPUT chain. It now lives in the
      # target container's namespace, so host UDP counters are the wrong place to look - kept
      # only to confirm that. Expect no Prometheus signature at all: cAdvisor does not expose
      # per-container UDP drops, and the application effect hides in the tail (p50 and p95 both
      # read BETTER than baseline while wall-clock time is 22x). If nothing moves, that is the
      # answer, and verify_injection records it as no_targets rather than pretending.
      dns_delay)            echo "host_udp_out:rate(node_netstat_Udp_OutDatagrams[1m])
front_net_rx:rate(container_network_receive_packets_total{name=~\"$FRONT\"}[1m])" ;;
      nagle_delayed_ack)    echo "tx_pkts:rate(container_network_transmit_packets_total{name=\"nagle-delayed-ack\"}[1m])
cpu:rate(container_cpu_usage_seconds_total{name=\"nagle-delayed-ack\"}[1m])" ;;
      code_lock_across_io|code_n_plus_one)
                            echo "cat_cpu:rate(container_cpu_usage_seconds_total{name=~\".*catalogue_1\$\"}[1m])
db_cpu:rate(container_cpu_usage_seconds_total{name=~\"$DB\"}[1m])" ;;
      code_event_loop_block|code_serial_awaits)
                            echo "front_cpu:rate(container_cpu_usage_seconds_total{name=~\"$FRONT\"}[1m])
front_fds:container_file_descriptors{name=~\"$FRONT\"}" ;;
      code_unbounded_cache) echo "front_mem:container_memory_usage_bytes{name=~\"$FRONT\"}" ;;
      *) echo "" ;;
    esac
}

q() {   # q <promql> -> a single number (max across series), or empty
    python3 - "$PROM" "$1" <<'PY' 2>/dev/null
import json, sys, urllib.parse, urllib.request
prom, expr = sys.argv[1], sys.argv[2]
url = prom + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
try:
    d = json.load(urllib.request.urlopen(url, timeout=10))
except Exception:
    sys.exit(0)
vals = [float(r["value"][1]) for r in d.get("data", {}).get("result", [])
        if r.get("value") and r["value"][1] not in ("NaN", "+Inf", "-Inf")]
# sum, not max. max silently picks one series, and on Train Ticket a `before` reading of 0.8264
# appeared for a container that did not exist yet - almost certainly a stale series winning the
# max. Summing is also what "how much of this is happening" actually means.
if vals:
    print(f"{sum(vals):.4f}")
PY
}

echo "=============================================================="
echo " MEASURING VERIFICATION TARGETS  -  app: $APP, hold ${HOLD_S}s"
echo " (a candidate that does not move is a result, not a failure)"
echo "=============================================================="

FAULTS=("$@")
[[ ${#FAULTS[@]} -eq 0 ]] && FAULTS=(lock_contention priority_inversion deadlock fd_exhaustion \
                                     conn_pool_exhaustion resource_abuse data_exfiltration \
                                     fork_storm dns_delay nagle_delayed_ack)

for f in "${FAULTS[@]}"; do
    recipe="$SD/$f.sh"
    [[ -f "$recipe" ]] || { echo; echo "--- $f: no recipe"; continue; }
    cands="$(candidates_for "$f")"
    [[ -z "$cands" ]] && { echo; echo "--- $f: no candidates defined"; continue; }

    echo
    echo "--- $f ---"
    # BEFORE. Sampled with load already running, because that is the state a campaign run's
    # baseline window is in - measuring against an idle system would overstate every ratio.
    declare -A before=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        before["${line%%:*}"]="$(q "${line#*:}")"
    done <<< "$cands"

    bash "$recipe" inject aggressive >/dev/null 2>&1 || { echo "  inject failed"; continue; }
    sleep "$HOLD_S"

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        k="${line%%:*}"; b="${before[$k]:-}"; a="$(q "${line#*:}")"
        if [[ -z "$b" || -z "$a" ]]; then
            printf "  %-12s before=%-12s during=%-12s  METRIC ABSENT\n" "$k" "${b:-none}" "${a:-none}"
        else
            printf "  %-12s before=%-12s during=%-12s  ratio=%s\n" "$k" "$b" "$a" \
                "$(python3 -c "b=$b; a=$a; print(f'{a/b:.2f}x' if b else ('inf' if a else '1.00x'))" 2>/dev/null || echo '?')"
        fi
    done <<< "$cands"

    bash "$recipe" cleanup >/dev/null 2>&1 || true
    sleep 5
done

echo
echo "=============================================================="
echo " Register ONLY the candidates that moved, with these numbers."
echo "=============================================================="
