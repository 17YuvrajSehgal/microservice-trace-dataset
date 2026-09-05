#!/bin/bash
# THE PILOT GATE. Run this before spending the v2 campaign.
#
# We do not get a second collection run, so the only protection against an unknown gap is to
# collect two runs, check everything, and fix what is broken while it is still cheap. Every
# check below exists because something in v1 failed silently and was found weeks later.
#
#   ./pilot_check.sh <run_dir>          check an already-collected run
#   ./pilot_check.sh --collect <name>   collect a run via run_gate.sh, then check it
#
# Exit code 0 = every blocking check passed.
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [[ "${1:-}" == "--collect" ]]; then
    RUN="${2:-pilot01}"
    echo "### collecting $RUN via run_gate.sh (60 s, 50 users) ###"
    "$SD/run_gate.sh" "$RUN" 60 50 || echo "(run_gate returned nonzero - checks will show why)"
    RUN_DIR="$HOME/traces/normal/$RUN"
    METRICS_DIR="$HOME/${RUN}_metrics"
else
    RUN_DIR="${1:?usage: pilot_check.sh <run_dir> | --collect <name>}"
    RUN="$(basename "$RUN_DIR")"
    METRICS_DIR="$HOME/${RUN}_metrics"
fi

pass=0; fail=0; warn=0
ok()   { echo "  PASS  $*"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $*"; fail=$((fail+1)); }
note() { echo "  WARN  $*"; warn=$((warn+1)); }

echo
echo "=============================================================="
echo " PILOT CHECK: $RUN_DIR"
echo "=============================================================="
[[ -d "$RUN_DIR" ]] || { echo "run directory does not exist - collection failed entirely"; exit 1; }

# ---------------------------------------------------------------- the four modalities ----
# The user's requirement: prove logs, metrics, traces AND kernel all actually arrived. In v1
# a modality could be empty and nothing said so.
echo
echo "--- 1. THE FOUR MODALITIES ---"

# kernel
KCTF=""
for c in "$RUN_DIR/kernel/kernel" "$RUN_DIR/kernel"; do
    [[ -f "$c/metadata" ]] && KCTF="$c" && break
done
if [[ -n "$KCTF" ]]; then
    nstream=$(ls "$KCTF"/channel0_* 2>/dev/null | wc -l)
    nev=$(babeltrace2 "$KCTF" 2>/dev/null | head -200000 | wc -l)
    if [[ "$nev" -gt 1000 ]]; then
        ok "kernel: $nstream per-CPU streams, $nev+ events decode"
    else
        bad "kernel: trace present but only $nev events decoded"
    fi
else
    bad "kernel: NO CTF metadata found - kernel tracing produced nothing"
fi

# spans (the trace modality)
SPANS="$RUN_DIR/otlp/spans.jsonl"
if [[ -s "$SPANS" ]]; then
    n=$(wc -l < "$SPANS")
    svc=$(grep -o '"serviceName":"[^"]*"' "$SPANS" 2>/dev/null | sort -u | wc -l)
    [[ "$n" -gt 10 ]] && ok "spans: $n spans from $svc services" \
                      || bad "spans: only $n lines - the collector may not be exporting"
else
    bad "spans: $SPANS missing or empty"
fi

# logs
if [[ -d "$RUN_DIR/logs" ]]; then
    nf=$(find "$RUN_DIR/logs" -type f -size +0 2>/dev/null | wc -l)
    nl=$(cat "$RUN_DIR"/logs/* 2>/dev/null | wc -l)
    [[ "$nf" -gt 3 ]] && ok "logs: $nf containers, $nl lines" \
                      || bad "logs: only $nf non-empty files"
else
    bad "logs: no logs directory"
fi

# metrics
if [[ -d "$METRICS_DIR" ]]; then
    nm=$(find "$METRICS_DIR" -type f -size +0 2>/dev/null | wc -l)
    empty=$(find "$METRICS_DIR" -type f -size -50c 2>/dev/null | wc -l)
    if [[ "$nm" -gt 3 ]]; then
        ok "metrics: $nm non-empty series files in $METRICS_DIR"
        [[ "$empty" -gt 0 ]] && note "metrics: $empty files look near-empty - check Prometheus was up"
    else
        bad "metrics: only $nm files - was Prometheus running?"
    fi
else
    bad "metrics: $METRICS_DIR missing"
fi

# ---------------------------------------------------------------- v2 additions -----------
echo
echo "--- 2. CONTAINER ATTRIBUTION (v2: three blueprints could not name a service) ---"
ENABLED="$RUN_DIR/meta/lttng_enabled_kernel.txt"
if [[ -s "$ENABLED" ]]; then
    ok "the enabled-event list was recorded"
    if grep -qE "cgroup_ns|pid_ns|net_ns" "$ENABLED"; then
        ok "namespace contexts are configured on the kernel channel"
    else
        bad "namespace contexts NOT in the session - attribution fix did not apply"
    fi
else
    bad "meta/lttng_enabled_kernel.txt missing"
fi

if [[ -n "$KCTF" ]]; then
    if babeltrace2 "$KCTF" 2>/dev/null | head -2000 | grep -qE "cgroup_ns|pid_ns|net_ns"; then
        ok "namespace ids are present ON EVENTS (not just configured)"
    else
        bad "namespace ids do NOT appear on decoded events"
    fi
fi

nsmap=$(ls "$RUN_DIR"/meta/proc_*_start.txt 2>/dev/null | wc -l)
[[ "$nsmap" -gt 3 ]] && ok "container->namespace map captured for $nsmap containers" \
                     || bad "container->namespace map missing - the join cannot be made"

echo
echo "--- 3. EVENT LOSS (v1 threw this away; a lossy run looks identical to a clean one) ---"
LOSS="$RUN_DIR/meta/event_loss.json"
if [[ -s "$LOSS" ]]; then
    if python3 -c "import json,sys; sys.exit(0 if json.load(open('$LOSS')).get('clean') else 1)" 2>/dev/null; then
        ok "no events discarded"
    else
        bad "EVENTS WERE DISCARDED - $(python3 -c "import json;d=json.load(open('$LOSS'));print(d.get('discarded_events'),'events')" 2>/dev/null)"
    fi
else
    bad "meta/event_loss.json missing - the capture did not run"
fi

echo
echo "--- 4. MEMORY + POWER TRACEPOINTS (v2 additions) ---"
if [[ -n "$KCTF" ]]; then
    if babeltrace2 "$KCTF" 2>/dev/null | head -400000 | grep -qE "vmscan|writeback"; then
        ok "memory tracepoints are firing (vmscan/writeback seen)"
    else
        note "no vmscan/writeback in the first 400k events - expected on an idle healthy run"
    fi
    if babeltrace2 "$KCTF" 2>/dev/null | head -400000 | grep -q "power_cpu"; then
        ok "power_* tracepoints are firing"
    else
        note "no power_cpu events in the first 400k - may be idle-state dependent"
    fi
fi

echo
echo "--- 5. CGROUP COUNTERS (per-run ground truth independent of our analysis) ---"
ncg=$(ls "$RUN_DIR"/meta/cgroup_*_start.txt 2>/dev/null | wc -l)
if [[ "$ncg" -gt 3 ]]; then
    ok "cgroup counters captured for $ncg containers"
    grep -l "memory.events" "$RUN_DIR"/meta/cgroup_*_start.txt >/dev/null 2>&1 \
        && ok "memory.events present (names which container hit its limit)" \
        || note "memory.events not found - check the cgroup path"
else
    bad "cgroup counters missing ($ncg files)"
fi

echo
echo "--- 6. CLOCKS + GROUND TRUTH ---"
grep -q clock_realtime_ns "$RUN_DIR/meta/runinfo_start.txt" 2>/dev/null \
    && ok "clock anchors recorded (cross-modality alignment)" \
    || bad "clock anchors missing"
[[ -f "$RUN_DIR/ground_truth.json" ]] && ok "ground_truth.json present" \
                                      || note "no ground_truth.json (expected for a normal run)"

echo
echo "--- 7. VERIFICATION IMAGE (v1: Sock Shop produced ZERO across 50 runs) ---"
if [[ -f "$RUN_DIR/verification.png" ]]; then
    ok "verification.png present"
elif [[ -f "$RUN_DIR/verification.json" ]]; then
    bad "verification.json exists but NO IMAGE - is python3-matplotlib installed?"
else
    note "no verification files (expected for a normal run; fault runs must have both)"
fi
python3 -c "import matplotlib" 2>/dev/null && ok "matplotlib importable on this VM" \
                                           || bad "matplotlib NOT importable - fault runs will have no image"

echo
echo "--- 8. SIZE (multiply by 308 for the campaign) ---"
sz=$(du -sb "$RUN_DIR" 2>/dev/null | cut -f1)
gb=$(python3 -c "print(f'{$sz/1e9:.2f}')" 2>/dev/null || echo "?")
echo "  run size: ${gb} GB uncompressed"
echo "  projected for 308 runs: $(python3 -c "print(f'{$sz*308/1e12:.2f}')" 2>/dev/null || echo '?') TB uncompressed"
echo "  (gzip of the CTF streams typically gives 3-4x)"

echo
echo "=============================================================="
printf " PILOT RESULT: %d passed, %d failed, %d warnings\n" "$pass" "$fail" "$warn"
if [[ "$fail" -eq 0 ]]; then
    echo " ALL BLOCKING CHECKS PASSED - the campaign can start"
else
    echo " *** $fail BLOCKING FAILURE(S) - fix before spending the campaign ***"
fi
echo "=============================================================="
exit $(( fail > 0 ? 1 : 0 ))
