#!/bin/bash
# extract_v2_full.sh - unpack the whole v2 release into a working tree on /scratch.
#
# EVERYTHING, including raw L0. v2 has no derived L1/L2/L3 - the bundles hold only what was
# collected: kernel CTF, OTLP spans, container logs, UST relay, meta/clock anchors, ground truth,
# verdicts, plus each run's Prometheus export and load CSV alongside.
#
#   bash extract_v2_full.sh --check    # space, inodes, and the measured CTF expansion. Extracts nothing
#   bash extract_v2_full.sh            # extract (resumable - re-run skips finished archives)
#   bash extract_v2_full.sh --verify   # count runs against the archives
#
#   env: SRC (/scratch/$USER/stratatrace/v2)
#        OUT (/scratch/$USER/stratatrace/data/stratatrace-v2)
#        PAR (16)  concurrent archives
#
# THE APPS STAY SEPARATE ON PURPOSE
# ---------------------------------
# Both applications use the SAME recipe names, so extracting them into one tree would merge
# anomaly_cpu/ from Sock Shop and Train Ticket into one directory. The run ids differ (tt_ prefix)
# so no run would be lost, but "how many anomaly_cpu runs are there" would stop having one answer.
# Output is $OUT/<app>/<recipe>/<run_id>/.
#
# THE CTF IS STILL GZIPPED AFTER THIS
# -----------------------------------
# package_run.sh compressed each kernel stream with pigz and left metadata+index plain, so a
# bundle holds channel0_*.gz. babeltrace cannot read those directly. This script does NOT gunzip
# them - that is a separate, much larger step, and --check measures what it would cost before you
# commit to it.
set -uo pipefail

ME="${USER:-$(id -un)}"
SRC="${SRC:-/scratch/$ME/stratatrace/v2}"
OUT="${OUT:-/scratch/$ME/stratatrace/data/stratatrace-v2}"
PAR="${PAR:-16}"
APPS="${APPS:-sockshop trainticket}"
UNZ="pigz -dc"; command -v pigz >/dev/null 2>&1 || UNZ="zcat"
STAMP="$OUT/.extracted"          # one marker per finished archive, so a timeout is resumable

[[ -d "$SRC" ]] || { echo "FATAL: no such source: $SRC"; exit 1; }

# ---------------------------------------------------------------------------- check ------------
if [[ "${1:-}" == "--check" ]]; then
    echo "=============================================================="
    echo " source: $SRC"
    echo "=============================================================="
    for app in $APPS; do
        n=$(ls "$SRC/$app"/*.tar.gz 2>/dev/null | wc -l)
        sz=$(du -sb "$SRC/$app" 2>/dev/null | cut -f1)
        printf "  %-13s %2d archives  %s\n" "$app" "$n" "$(numfmt --to=iec "${sz:-0}")"
    done
    echo
    echo "=============================================================="
    echo " destination: $OUT"
    echo "=============================================================="
    df -h "$(dirname "$OUT")" 2>/dev/null | tail -1
    command -v diskusage_report >/dev/null && diskusage_report 2>/dev/null | grep -E "scratch|Description"
    echo
    echo "=============================================================="
    echo " what extraction costs"
    echo "=============================================================="
    echo "  Stage 1 - tarballs to bundles: ~1.18 TB and ~831,000 files."
    echo "            (that is the packed size; the CTF inside stays gzipped)"
    echo
    echo "  Stage 2 - gunzip the CTF so babeltrace can read it: measuring a real bundle..."
    # Measure rather than guess. gzip -l is unreliable past 4 GB (32-bit ISIZE), so decompress a
    # few real streams and weigh them.
    A=$(ls "$SRC"/*/anomaly_cpu.tar.gz 2>/dev/null | head -1)
    if [[ -n "$A" ]]; then
        TMP=$(mktemp -d)
        $UNZ "$A" | tar -xf - -C "$TMP" --wildcards '*/kernel/kernel/channel0_0.gz' 2>/dev/null || true
        G=$(find "$TMP" -name 'channel0_0.gz' | head -1)
        if [[ -n "$G" ]]; then
            c=$(stat -c%s "$G")
            u=$($UNZ "$G" | wc -c)
            echo "    sample stream: $(numfmt --to=iec "$c") gz  ->  $(numfmt --to=iec "$u") raw"
            python3 - "$c" "$u" <<'PY' 2>/dev/null || echo "    ratio: $u / $c"
import sys
c, u = int(sys.argv[1]), int(sys.argv[2])
print("    expansion ratio: %.1fx" % (u / c) if c else "    n/a")
print("    so the CTF portion of 1.18 TB would become roughly %.1f TB" % (1.18 * (u / c)) if c else "")
print("    (upper bound - only the kernel streams expand, not spans/logs/metrics)")
PY
        else
            echo "    could not sample a stream from $A"
        fi
        rm -rf "$TMP"
    else
        echo "    no anomaly_cpu.tar.gz to sample"
    fi
    echo
    echo "  Nothing was extracted. Run without --check to do stage 1."
    exit 0
fi

# --------------------------------------------------------------------------- verify ------------
if [[ "${1:-}" == "--verify" ]]; then
    echo "== runs extracted under $OUT =="
    tot=0
    for app in $APPS; do
        n=$(find "$OUT/$app" -mindepth 3 -maxdepth 4 -path '*/meta/runinfo_end.txt' 2>/dev/null | wc -l)
        printf "  %-13s %4d runs\n" "$app" "$n"; tot=$((tot+n))
    done
    echo "  TOTAL: $tot   (expect 303: 169 sockshop + 134 trainticket)"
    echo "  files: $(find "$OUT" -type f 2>/dev/null | wc -l)"
    du -sh "$OUT" 2>/dev/null
    exit 0
fi

# -------------------------------------------------------------------------- extract ------------
mkdir -p "$OUT" "$STAMP"
echo "== $SRC -> $OUT   (PAR=$PAR, $UNZ, archives left INTACT) =="

extract_one() {
    local app="$1" a="$2"
    local rec; rec="$(basename "$a" .tar.gz)"
    local mark="$STAMP/${app}-${rec}"
    if [[ -f "$mark" ]]; then echo "  SKIP $app/$rec (done)"; return 0; fi
    mkdir -p "$OUT/$app"
    if $UNZ "$a" | tar -xf - -C "$OUT/$app"; then
        # Mark AFTER success, so a killed job re-does the archive it was mid-way through rather
        # than leaving a half-extracted recipe that looks finished.
        touch "$mark"; echo "  ok   $app/$rec"
    else
        echo "  FAIL $app/$rec"; return 1
    fi
}
export -f extract_one; export OUT STAMP UNZ

rc=0
for app in $APPS; do
    ls "$SRC/$app"/*.tar.gz 2>/dev/null \
        | xargs -P "$PAR" -I{} bash -c 'extract_one "$0" "$1"' "$app" {} || rc=1
done

echo
bash "$0" --verify
[[ "$rc" -eq 0 ]] || echo "!! at least one archive failed - re-run to retry only those"
exit "$rc"
