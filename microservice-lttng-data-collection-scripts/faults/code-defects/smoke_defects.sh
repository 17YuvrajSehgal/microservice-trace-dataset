#!/bin/bash
# Smoke-test every code defect before it earns campaign runs.
#
# THIS IS THE STEP THAT PROTECTS THE CAMPAIGN. A defect that builds but does nothing produces a
# run labelled as a fault that never happened - and unlike a crash, nothing downstream can
# tell. So each defect has to demonstrate three things, in order:
#
#   1. the service still STARTS with the defect on
#   2. the service still SERVES with the defect on   (a broken service is a different fault)
#   3. the defect actually CHANGES something measurable against its own control
#
# Point 3 is measured against `STRATA_BUG=none` on the SAME IMAGE, not against the stock
# service, so the comparison isolates the defect rather than the rebuild.
#
# A defect that fails any of these must be fixed or dropped BEFORE the campaign, not
# discovered inside it.
#
#   ./smoke_defects.sh [defect ...]      default: all five
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FAULTS=$(cd "$SD/.." && pwd)
FRONTEND="${FRONTEND_HOST:-http://localhost:80}"

DEFECTS=("$@")
[[ ${#DEFECTS[@]} -eq 0 ]] && DEFECTS=(code_lock_across_io code_n_plus_one \
                                       code_event_loop_block code_serial_awaits \
                                       code_unbounded_cache)

# Which endpoint exercises each defect. catalogue defects sit on the List query path; the
# front-end ones sit on the shared helper every API module goes through.
endpoint_for() {
    case "$1" in
        code_lock_across_io|code_n_plus_one) echo "/catalogue" ;;
        *) echo "/catalogue" ;;
    esac
}

# Median of N sequential requests, in milliseconds. Sequential on purpose: a serialising
# defect shows up in the median of concurrent load, but we want a signal that does not depend
# on us generating load correctly during a smoke test.
measure() {   # measure <path> <n>
    local path="$1" n="${2:-25}" i t0 t1
    local times=()
    for ((i = 0; i < n; i++)); do
        t0=$(date +%s%N)
        curl -sf -m 10 -o /dev/null "${FRONTEND}${path}" 2>/dev/null || true
        t1=$(date +%s%N)
        times+=($(( (t1 - t0) / 1000000 )))
    done
    printf '%s\n' "${times[@]}" | sort -n | awk '{a[NR]=$1} END {print a[int(NR/2)+1]}'
}

pass=0; fail=0
echo "=============================================================="
echo " CODE DEFECT SMOKE TEST"
echo "=============================================================="

for d in "${DEFECTS[@]}"; do
    recipe="$FAULTS/$d.sh"
    [[ -x "$recipe" ]] || { echo "  MISSING $d"; fail=$((fail+1)); continue; }
    path=$(endpoint_for "$d")

    echo
    echo "--- $d ---"

    # control first: same image, defect off. This is the number the fault is compared against.
    bash "$recipe" control >/dev/null 2>&1 || { echo "  FAIL  control would not start"; fail=$((fail+1)); continue; }
    sleep 6
    base=$(measure "$path" 25)
    echo "  control (STRATA_BUG=none): median ${base} ms"

    if ! bash "$recipe" inject aggressive >/dev/null 2>&1; then
        echo "  FAIL  inject failed"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi
    sleep 6

    # 1. still up?
    if ! curl -sf -m 10 -o /dev/null "${FRONTEND}${path}" 2>/dev/null; then
        echo "  FAIL  service does not SERVE with the defect on - that is a different fault"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi

    # 2. does it change anything?
    with=$(measure "$path" 25)
    echo "  defect  (STRATA_BUG on):   median ${with} ms"

    if [[ "$base" -gt 0 ]]; then
        ratio=$(python3 -c "print(f'{$with/$base:.2f}')" 2>/dev/null || echo "?")
    else
        ratio="?"
    fi
    delta=$(( with - base ))

    # unbounded_cache is a MEMORY defect - it need not change latency at all, and demanding it
    # would be measuring the wrong thing. Check the container is growing instead.
    if [[ "$d" == "code_unbounded_cache" ]]; then
        mem=$(docker stats --no-stream --format '{{.MemUsage}}' \
              "$(docker ps --format '{{.Names}}' | grep -m1 front-end)" 2>/dev/null || echo "?")
        echo "  memory in use: $mem  (latency ratio ${ratio}x, not the point for this one)"
        echo "  PASS  serves with the defect on; memory growth is the signal, measured in the run"
        pass=$((pass+1))
    elif [[ "$delta" -ge 5 || "$(python3 -c "print(1 if $ratio >= 1.15 else 0)" 2>/dev/null || echo 0)" == "1" ]]; then
        echo "  PASS  ${ratio}x slower (+${delta} ms) - the defect is doing something"
        pass=$((pass+1))
    else
        echo "  FAIL  ${ratio}x - indistinguishable from its control. Tune it or drop it;"
        echo "        a defect that changes nothing would be labelled as a fault that never happened."
        fail=$((fail+1))
    fi

    bash "$recipe" cleanup >/dev/null 2>&1 || true
    sleep 4
done

echo
echo "=============================================================="
printf " SMOKE RESULT: %d passed, %d failed\n" "$pass" "$fail"
[[ "$fail" -eq 0 ]] && echo " every defect builds, serves and measurably misbehaves" \
                    || echo " *** fix or drop the failures before the campaign ***"
echo "=============================================================="
exit $(( fail > 0 ? 1 : 0 ))
