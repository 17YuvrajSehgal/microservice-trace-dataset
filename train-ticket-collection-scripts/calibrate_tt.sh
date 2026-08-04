#!/bin/bash
# Train Ticket fault calibration harness. With steady booking load running, injects each fault for
# a short window and measures: the canonical Prometheus signal (baseline vs injected mean), a
# client KPI (search latency), and stack liveness. Prints a table so the CALIBRATE thresholds in
# verification_targets_tt.json can be set from real data + safety confirmed (esp. anomaly_mem not
# OOM-ing the 64GB box). Read-mostly: every fault is cleaned up and the stack rechecked between.
#
#   ./calibrate_tt.sh 2>&1 | tee ~/tt_calibrate.out
set -uo pipefail
TTD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FAULTS="$(cd "$TTD/.." && pwd)/microservice-lttng-data-collection-scripts/faults"
PROM="${PROMETHEUS:-http://localhost:9090}"
export CONTAINER_PREFIX=trainticket FAULT_STATE_DIR="$HOME/fault-state/cal"
BASE_S=30; SETTLE_S=25; MEAS_S=30

# avg of a promql over the last ${1}s (returns 'none' if empty)
qavg() { curl -s "$PROM/api/v1/query" --data-urlencode "query=avg_over_time((${2})[${1}s:5s])" \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['data']['result'];print(round(float(d[0]['value'][1]),6) if d else 'none')" 2>/dev/null || echo err; }
login() { curl -s -X POST http://localhost:8080/api/v1/users/login -H 'Content-Type: application/json' \
  -d '{"username":"fdse_microservice","password":"111111"}'; }
srch_ms() { local t=$(login | grep -o '"token":"[^"]*' | cut -d'"' -f4); local d=$(date -d '+3 days' +%Y-%m-%d)
  curl -s -o /dev/null -w '%{time_total}' -X POST http://localhost:8080/api/v1/travelservice/trips/left \
    -H 'Content-Type: application/json' -H "Authorization: Bearer $t" \
    -d "{\"startPlace\":\"shanghai\",\"endPlace\":\"suzhou\",\"departureTime\":\"$d\"}"; }
alive() { local c=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/api/v1/users/login \
  -H 'Content-Type: application/json' -d '{"username":"fdse_microservice","password":"111111"}'); echo "$c"; }

# name | recipe | intensity | inject-env | canonical promql
CASES=(
"anomaly_mem_sub|anomaly_mem|subtle||node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes"
"anomaly_mem_agg|anomaly_mem|aggressive||node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes"
"anomaly_cpu|anomaly_cpu|aggressive||100 - (avg(rate(node_cpu_seconds_total{mode=\"idle\"}[1m])) * 100)"
"anomaly_disk|anomaly_disk|aggressive||rate(node_disk_io_time_seconds_total[1m])"
"noisy_sub|noisy_neighbor|subtle||rate(container_cpu_usage_seconds_total{name=~\".*noisy-neighbor.*\"}[1m])"
"svc_cpu_sub|svc_cpu_cap|subtle|TARGET_SVC=ts-travel-service|rate(container_cpu_usage_seconds_total{name=~\".*ts-travel-service_1\$\"}[1m])"
"svc_cpu_agg|svc_cpu_cap|aggressive|TARGET_SVC=ts-travel-service|rate(container_cpu_usage_seconds_total{name=~\".*ts-travel-service_1\$\"}[1m])"
"svc_mem_agg|svc_mem_cap|aggressive|TARGET_SVC=ts-order-service|min(container_spec_memory_limit_bytes{name=~\".*ts-order-service_1\$\"})"
"dep_outage|dependency_outage|aggressive|TARGET_SVC=ts-seat-service|rate(container_cpu_usage_seconds_total{name=~\".*ts-seat-service_1\$\"}[1m])"
"slow_db_sub|slow_db|subtle|PROXY=mysql TARGET_SERVICE=mysql FAULT_NAME=slow_db_mysql|rate(container_cpu_usage_seconds_total{name=\"mysql\"}[1m])"
"slow_db_agg|slow_db|aggressive|PROXY=mysql TARGET_SERVICE=mysql FAULT_NAME=slow_db_mysql|rate(container_cpu_usage_seconds_total{name=\"mysql\"}[1m])"
"svc_net_agg|svc_net|aggressive|TARGET_SVC=ts-basic-service|rate(container_network_transmit_bytes_total{name=~\".*ts-basic-service_1\$\"}[1m])"
"anomaly_net|anomaly_net|aggressive||rate(container_network_receive_bytes_total{name=\"mysql\"}[1m])"
)

printf "%-14s %-9s | %-12s %-12s | %-8s %-8s | %s\n" case intensity base_metric inj_metric base_ms inj_ms alive
echo "-------------------------------------------------------------------------------------------------"
for row in "${CASES[@]}"; do
  IFS='|' read -r name recipe intensity env promql <<< "$row"
  rm -rf "$FAULT_STATE_DIR"; mkdir -p "$FAULT_STATE_DIR"
  bm=$(qavg $BASE_S "$promql"); bms=$(srch_ms)
  env $env bash "$FAULTS/${recipe}.sh" inject "$intensity" >/dev/null 2>&1 || echo "  ($name inject WARN)"
  sleep $SETTLE_S
  im=$(qavg $MEAS_S "$promql"); ims=$(srch_ms); al=$(alive)
  env $env bash "$FAULTS/${recipe}.sh" cleanup >/dev/null 2>&1 || true
  printf "%-14s %-9s | %-12s %-12s | %-8s %-8s | %s\n" "$name" "$intensity" "$bm" "$im" "$bms" "$ims" "$al"
  sleep 12   # recovery before next fault
done
echo "=== calibration done; stack alive: $(alive) ==="
