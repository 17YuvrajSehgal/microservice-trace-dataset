#!/bin/bash
# Train Ticket fault-run driver. Thin wrapper: export the TT app profile, then delegate the
# baseline -> inject -> recovery -> metrics -> verify -> audit orchestration to the SHARED
# run_scenario.sh (identical methodology to the Sock Shop Phase-2 campaign - "same as OB").
#
#   run_scenario_tt.sh <recipe> <intensity> [run_id] [users]
#     <recipe> = a script in ../microservice-lttng-data-collection-scripts/faults/ (e.g. slow_db,
#                svc_cpu_cap, error_storm), or "normal" for a fault-free reference run.
#
# The campaign driver (run_campaign_tt.sh) sets TARGET_SVC + EXPECTED_BLAST_RADIUS per fault from
# FAULTS-TT.md; a standalone run picks the recipe defaults. VM-only (LTTng + fault injection).
#   nohup ./run_scenario_tt.sh svc_cpu_cap subtle ttc_r01 20 > /tmp/ttc_r01.out 2>&1 &
set -uo pipefail
TTD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)                    # train-ticket-collection-scripts
STRATA_REPO="${STRATA_REPO:-$(cd "$TTD/.." && pwd)}"
SD="$STRATA_REPO/microservice-lttng-data-collection-scripts"        # shared collection tooling

# TT app profile: consumed by collect_trace.sh (container snapshots + LTTng session name), the
# fault recipes (CONTAINER_PREFIX -> trainticket_<svc>_1), and the derivers (service_map).
export TRACE_APP=trainticket
export STRATATRACE_APP=trainticket
export CONTAINER_PREFIX=trainticket
export CONTAINER_REGEX="${CONTAINER_REGEX:-trainticket_.*_1|^mysql$|^nacos$}"
export LOG_CONTAINER_REGEX="${LOG_CONTAINER_REGEX:-trainticket_.*_1|^mysql$|^nacos$|^otel-collector$}"
export OTLP_SRC="${OTLP_SRC:-$TTD/otlp-out/spans.jsonl}"
export LOAD_GEN="$TTD/load_generator.py"                            # the TT booking load generator
export FRONTEND_HOST="${FRONTEND_HOST:-http://localhost:8080}"     # TT front door (Sock Shop = :80)
export VERIFY_TARGETS="${VERIFY_TARGETS:-$TTD/verification_targets_tt.json}"  # cAdvisor/node QC panel
export TOXIPROXY_API="${TOXIPROXY_API:-http://localhost:8474}"     # slow_db/error_storm toxics

exec "$SD/run_scenario.sh" "$@"
