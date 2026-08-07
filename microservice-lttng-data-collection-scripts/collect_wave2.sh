#!/bin/bash
# collect_wave2.sh - one-command wave-2 collection (see ../dataset-collection-gaps.md).
#
# Fills the MSR-critical gaps left after the v1 40-run campaign:
#   - F2/F3/F4 host disk/mem/net stressors -> RQ1's "confusable resource faults" set
#   - memory-tracepoint runs (KERNEL_MEM=1: anomaly_mem, svc_mem_cap) -> kernel modality
#     on memory-layer faults (F3/F8) + the memory-leak/gc agentic skills
#   - per-service netem (svc_net, F12) -> service-localized network fault
#
# Wraps run_scenario.sh, which already does: collect_trace(+KERNEL_MEM) -> full
# Prometheus export -> verify_injection -> audit_alignment. Run on the VM with
# the Sock Shop stack UP.
#
#   ./collect_wave2.sh [--dry-run] [group ...]
#     groups: host mem netem subtle    (default: host mem netem)
#   env: REPEATS(3) SUB_REPEATS(2) INJECTION_S(120) USERS(200) PROFILE(steady)
#        PROMETHEUS FRONTEND_HOST
#
# RQ4 collection-overhead matrix is a SEPARATE protocol - see the fair-overhead
# harness (run_reviewer_overhead_*.sh), not this script.
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPEATS="${REPEATS:-3}"; SUB="${SUB_REPEATS:-2}"
export INJECTION_S="${INJECTION_S:-120}"
PROFILE="${PROFILE:-steady}"; export PROFILE

DRY=0; REQ=()
for a in "$@"; do case "$a" in --dry-run|-n) DRY=1 ;; *) REQ+=("$a") ;; esac; done
[ ${#REQ[@]} -eq 0 ] && REQ=(host mem netem)
in_req() { local g; for g in "${REQ[@]}"; do [ "$g" = "$1" ] && return 0; done; return 1; }

# group | recipe | intensity | kernel_mem | target_svc | repeats
MATRIX=(
  "host|anomaly_disk|aggressive|0||$REPEATS"
  "host|anomaly_net|aggressive|0||$REPEATS"
  "mem|anomaly_mem|aggressive|1||$REPEATS"
  "mem|svc_mem_cap|aggressive|1|carts|$REPEATS"
  "netem|svc_net|aggressive|0|carts|$REPEATS"
  "subtle|anomaly_disk|subtle|0||$SUB"
  "subtle|anomaly_mem|subtle|1||$SUB"
)

echo "=== wave-2 plan  (groups: ${REQ[*]}; inject=${INJECTION_S}s; profile=$PROFILE) ==="
PLAN=()
for row in "${MATRIX[@]}"; do
  IFS='|' read -r grp recipe inten kmem svc reps <<< "$row"
  in_req "$grp" || continue
  for i in $(seq 1 "$reps"); do PLAN+=("$grp|$recipe|$inten|$kmem|$svc|$i"); done
done
i=0; for p in "${PLAN[@]}"; do
  IFS='|' read -r grp recipe inten kmem svc n <<< "$p"; i=$((i+1))
  printf "  %2d. %-13s %-11s kernel_mem=%s svc=%-5s r%s\n" "$i" "$recipe" "$inten" "$kmem" "${svc:-none}" "$n"
done
echo "total: ${#PLAN[@]} runs  (~$(( ${#PLAN[@]} * (60 + INJECTION_S + 60) / 60 ))+ min collect, plus metrics/verify/audit)"
[ "$DRY" = 1 ] && { echo "(dry-run) nothing executed."; exit 0; }

echo; echo "=== running ==="
declare -A VERD
for p in "${PLAN[@]}"; do
  IFS='|' read -r grp recipe inten kmem svc n <<< "$p"
  RUN="${recipe}_${inten}_${PROFILE}_r${n}"
  echo "--- [$RUN]  kernel_mem=$kmem  svc=${svc:-none} ---"
  KERNEL_MEM="$kmem" TARGET_SVC="${svc:-}" "$SD/run_scenario.sh" "$recipe" "$inten" "$RUN" "${USERS:-200}" || echo "[$RUN] run_scenario returned nonzero"
  RD="$HOME/traces/$recipe/$RUN"
  # Compress the kernel CTF streams (~6x) now the inline audit has run - matches the
  # v1 storage format (run_campaign.sh does the same) and keeps each run ~3 GB instead
  # of ~20 GB (raw), which the resource-stress + KERNEL_MEM runs otherwise balloon to.
  # metadata/index stay raw; derivers/babeltrace gunzip on demand. Sequential -> no
  # perturbation of live tracing.
  [ -d "$RD/kernel/kernel" ] && gzip -q "$RD"/kernel/kernel/channel0_* 2>/dev/null || true
  V=$(python3 -c "import json;print(json.load(open('$RD/verification.json')).get('verification_status','n/a'))" 2>/dev/null || echo n/a)
  VERD["$RUN"]="$V"
  echo "[$RUN] -> $V"
done

echo; echo "=== wave-2 summary ==="
for k in "${!VERD[@]}"; do printf "  %-42s %s\n" "$k" "${VERD[$k]}"; done | sort
CONF=$(printf '%s\n' "${VERD[@]}" | grep -c confirmed || true)
echo "confirmed: $CONF / ${#VERD[@]}"
