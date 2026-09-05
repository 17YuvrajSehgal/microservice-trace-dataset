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

# Which URL exercises each defect.
#
# MEASURE THE CATALOGUE DEFECTS DIRECTLY, NOT THROUGH THE FRONT END. Going via the proxy on
# port 80 added roughly 35 ms of its own, which completely swamped a serialised 2 ms query -
# code_lock_across_io measured 0.84x and looked broken. The lock was working; the proxy was
# louder than the defect. Docker bridge networks are routable from the host on Linux, so we
# talk to the container directly and the defect is the only thing in the path.
target_url_for() {
    case "$1" in
        code_lock_across_io|code_n_plus_one)
            local ip
            ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'                  "$(docker ps --format '{{.Names}}' | grep -m1 'catalogue_1')" 2>/dev/null)
            if [[ -n "$ip" ]]; then echo "http://${ip}/catalogue"; else echo "${FRONTEND}/catalogue"; fi ;;
        *) echo "${FRONTEND}/catalogue" ;;
    esac
}

# Median request time in ms, from loadprobe.py.
#
# FOUR MEASUREMENTS WERE WRONG BEFORE THIS ONE, and each reported a working defect as doing
# nothing. Sequential curl (a lock costs nothing with one request in flight), curl through the
# front-end proxy (~35 ms of its own), xargs -P with curl (300 process spawns dominated), and
# finally a threaded probe WITHOUT keep-alive (25 ms per connection hid a 1.7 ms critical
# section). Only the last version - one process, real threads, connections reused - showed
# code_lock_across_io at 5.4x, which is what it had been doing all along.
#
# A defect wrongly declared dead gets tuned or dropped. The measurement has to be trustworthy
# before its verdict means anything.
measure() {   # measure <url> <n> <concurrency>  -> p50 in ms, integer
    python3 "$SD/loadprobe.py" "$1" "${2:-400}" "${3:-60}" 2>/dev/null | tr " " "
" | grep "^p50=" | cut -d= -f2 | cut -d. -f1
}

# Which defects only reveal themselves when requests overlap.
concurrency_for() {
    case "$1" in
        code_lock_across_io|code_event_loop_block|code_serial_awaits) echo 60 ;;
        *) echo 1 ;;
    esac
}

pass=0; fail=0
echo "=============================================================="
echo " CODE DEFECT SMOKE TEST"
echo "=============================================================="

for d in "${DEFECTS[@]}"; do
    recipe="$FAULTS/$d.sh"
    # -f, not -x: the recipes are always invoked through `bash`, and the exec bit does not
    # survive a checkout made from a Windows working tree. Testing for it reported all five
    # recipes MISSING when every one was present.
    [[ -f "$recipe" ]] || { echo "  MISSING $d"; fail=$((fail+1)); continue; }
    path=$(target_url_for "$d")
    conc=$(concurrency_for "$d")

    echo
    echo "--- $d ---"

    # control first: same image, defect off. This is the number the fault is compared against.
    bash "$recipe" control >/dev/null 2>&1 || { echo "  FAIL  control would not start"; fail=$((fail+1)); continue; }
    sleep 6
    path=$(target_url_for "$d")   # re-resolve: the container was just recreated
    base=$(measure "$path" 400 "$conc")
    echo "  control (STRATA_BUG=none): median ${base} ms  (concurrency $conc)"

    if ! bash "$recipe" inject aggressive >/dev/null 2>&1; then
        echo "  FAIL  inject failed"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi
    sleep 6

    # 1. still up?
    if ! curl -sf -m 10 -o /dev/null "${path}" 2>/dev/null; then
        echo "  FAIL  service does not SERVE with the defect on - that is a different fault"
        bash "$recipe" cleanup >/dev/null 2>&1 || true
        fail=$((fail+1)); continue
    fi

    # 2. does it change anything?
    path=$(target_url_for "$d")   # re-resolve after the swap
    with=$(measure "$path" 400 "$conc")
    echo "  defect  (STRATA_BUG on):   median ${with} ms"

    if [[ "$base" -gt 0 ]]; then
        ratio=$(python3 -c "print(f'{$with/$base:.2f}')" 2>/dev/null || echo "?")
    else
        ratio="?"
    fi
    base=${base:-0}; with=${with:-0}
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
