#!/bin/bash
# decompress_v2_tree.sh - leave NO .gz in the v2 working tree.
#
# Everything directly readable: babeltrace opens the CTF without a decode cache, and the metric
# exports are plain JSON.
#
#   bash decompress_v2_tree.sh --check    # count, measure the real ratio, check free space
#   bash decompress_v2_tree.sh            # decompress in place (resumable)
#   bash decompress_v2_tree.sh --verify   # assert zero .gz remain
#
#   env: OUT (/scratch/$USER/stratatrace/data/stratatrace-v2)  PAR (64)
#
# IT IS NOT JUST THE KERNEL TRACES
# --------------------------------
# Measured on the extracted tree: 145,981 .gz files, of which only ~4,000 are kernel
# channelN_N.gz. The other ~142,000 are the per-run Prometheus export - roughly 440 metric series
# per run, each its own gzipped JSON. Decompressing "the traces" alone would have left 97% of the
# gz files in place.
#
# RESUMABLE FOR FREE
# ------------------
# pigz -d removes the .gz only after the plain file is written, so a killed job leaves finished
# files gone from the work list and half-done ones untouched. Re-running simply finds fewer.
set -uo pipefail

ME="${USER:-$(id -un)}"
OUT="${OUT:-/scratch/$ME/stratatrace/data/stratatrace-v2}"
PAR="${PAR:-64}"
UNZ="pigz -d"; command -v pigz >/dev/null 2>&1 || UNZ="gunzip"

[[ -d "$OUT" ]] || { echo "FATAL: no such tree: $OUT"; exit 1; }

count_gz() { find "$OUT" -name '*.gz' -type f 2>/dev/null | wc -l; }

# Sample real files to get the expansion ratio. gzip -l is unreliable past 4 GB (32-bit ISIZE),
# and the two populations here differ wildly - big binary CTF streams against small JSON - so
# sample each separately rather than averaging a number that describes neither.
measure() {
    local pat="$1" label="$2" n=0 c=0 u=0
    while read -r f; do
        [[ -z "$f" ]] && continue
        local cs us
        cs=$(stat -c%s "$f") || continue
        us=$($UNZ -c "$f" 2>/dev/null | wc -c) || continue
        c=$((c+cs)); u=$((u+us)); n=$((n+1))
    done < <(find "$OUT" -name "$pat" -type f 2>/dev/null | head -"${3:-12}")
    if [[ "$n" -gt 0 && "$c" -gt 0 ]]; then
        printf '  %-28s %3d sampled  %.1fx  (%s gz -> %s raw)\n' "$label" "$n" \
            "$(python3 -c "print($u/$c)")" \
            "$(numfmt --to=iec $c)" "$(numfmt --to=iec $u)"
        python3 -c "print($u/$c)"
    else
        echo "  $label: nothing to sample" >&2; echo 1
    fi
}

if [[ "${1:-}" == "--check" ]]; then
    echo "=============================================================="
    echo " $OUT"
    echo "=============================================================="
    tot=$(count_gz)
    kern=$(find "$OUT" -name 'channel*_*.gz' -type f 2>/dev/null | wc -l)
    echo "  .gz files: $tot   (kernel streams: $kern, everything else: $((tot-kern)))"
    cbytes=$(find "$OUT" -name '*.gz' -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')
    echo "  compressed: $(numfmt --to=iec "$cbytes")"
    echo
    echo "  measured expansion (samples, not estimates):"
    rk=$(measure 'channel*_*.gz' 'kernel CTF streams' 8 | tail -1)
    rj=$(measure '*.json.gz'     'Prometheus metric JSON' 40 | tail -1)
    echo
    kb=$(find "$OUT" -name 'channel*_*.gz' -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')
    jb=$((cbytes - kb))
    python3 - "$kb" "$jb" "$rk" "$rj" <<'PY'
import sys
kb, jb, rk, rj = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
raw = kb*rk + jb*rj
g = 1024**3
print("  projected raw total : %.1f GiB" % (raw/g))
print("  currently occupies  : %.1f GiB" % ((kb+jb)/g))
print("  NET ADDITIONAL need : %.1f GiB" % ((raw-kb-jb)/g))
PY
    echo
    echo "  free now:"
    df -h "$OUT" 2>/dev/null | tail -1
    command -v diskusage_report >/dev/null && diskusage_report 2>/dev/null | grep -E "scratch|Description"
    echo
    echo "  File COUNT does not change - each .gz becomes one plain file."
    echo "  Nothing was decompressed."
    exit 0
fi

if [[ "${1:-}" == "--verify" ]]; then
    n=$(count_gz)
    echo "  .gz remaining: $n"
    if [[ "$n" -eq 0 ]]; then echo "  OK - the tree is fully decompressed"; else
        echo "  still compressed, a sample:"; find "$OUT" -name '*.gz' -type f 2>/dev/null | head -5
    fi
    echo "  runs: $(find "$OUT" -path '*/meta/runinfo_end.txt' 2>/dev/null | wc -l)  (expect 303)"
    du -sh "$OUT" 2>/dev/null
    [[ "$n" -eq 0 ]]
    exit $?
fi

N=$(count_gz)
echo "== decompressing $N .gz in place under $OUT (PAR=$PAR, $UNZ) =="
[[ "$N" -eq 0 ]] && { echo "nothing to do"; exit 0; }

# -f so a leftover plain file from an interrupted run does not stall the whole batch on a prompt.
find "$OUT" -name '*.gz' -type f -print0 2>/dev/null \
    | xargs -0 -P "$PAR" -n 40 $UNZ -f
rc=$?

echo
left=$(count_gz)
echo "== done: $left .gz remaining (started with $N), rc=$rc =="
[[ "$left" -eq 0 ]] || echo "!! some failed - re-run to retry only those"
du -sh "$OUT" 2>/dev/null
exit "$rc"
