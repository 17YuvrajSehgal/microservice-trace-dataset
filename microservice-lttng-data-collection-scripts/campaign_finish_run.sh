#!/bin/bash
# What happens to a run AFTER run_scenario returns: package it, record whether the trace was
# clean, and move it off the collection disk.
#
# ONE IMPLEMENTATION, called by both application drivers.
#
# They had drifted apart already. run_campaign.sh packaged runs and captured event loss;
# run_campaign_tt.sh did neither - it only gzipped. So Train Ticket runs would have arrived with
# no MANIFEST.json, no checksums, no usable/not verdict and no record of whether LTTng dropped
# anything, and nobody would have noticed until the two halves of the dataset were compared.
# That is the same divergence that left v1 with 50 runs on one application and 43 on the other.
#
# WHY THE ARCHIVE MOVE IS NOT OPTIONAL
# ------------------------------------
# Measured 5 Sept, packed size per 240 s run: Sock Shop ~2.3 GB, Train Ticket ~6 GB.
#
#     Sock Shop     169 runs x 2.3 GB = 389 GB   against 179 GB free on /
#     Train Ticket  134 runs x 6.0 GB = 804 GB   against 127 GB free on /
#
# Without moving them, Sock Shop fills the root disk around run 78 and Train Ticket around run
# 21. Both archives are 1 TB and were sitting empty.
#
#   bash campaign_finish_run.sh <run_dir> <run_id>
#   env: ARCHIVE_DIR (/mnt/archive/runs)  KEEP_LOCAL=1 to skip the move
set -uo pipefail
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${1:?usage: campaign_finish_run.sh <run_dir> <run_id>}"
RUN_ID="${2:-$(basename "$RUN_DIR")}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/mnt/archive/runs}"

[[ -d "$RUN_DIR" ]] || { echo "[finish] no such run dir: $RUN_DIR"; exit 1; }

# 1. Package: compresses the CTF with pigz, writes MANIFEST.json with checksums and a
#    usable/not verdict. Compression lives HERE and nowhere else - the drivers used to gzip
#    first, single-threaded, which left package_run's pigz nothing to do and cost ~7 minutes a
#    run on one core out of sixteen.
bash "$SD/package_run.sh" "$RUN_DIR" || echo "[finish] WARN: package_run failed for $RUN_ID"

# 2. Did LTTng drop anything? Reported only at `lttng stop`, and v1 threw it away - so a run
#    that lost a third of its events was indistinguishable from a clean one.
LOSS="n/a"
if [[ -f "$RUN_DIR/meta/event_loss.json" ]]; then
    LOSS=$(python3 -c "
import json
d = json.load(open('$RUN_DIR/meta/event_loss.json'))
print('clean' if d.get('clean') else 'LOSSY:%d' % d.get('discarded_events', 0))" 2>/dev/null || echo n/a)
fi

# 3. Off the collection disk. The aux files (metrics export, load CSV) travel beside the bundle,
#    because the transfer layer packages them into _aux_metrics_load.tar.gz separately - they
#    are deliberately NOT inside the run dir.
MOVED="kept-local"
if [[ "${KEEP_LOCAL:-0}" != "1" ]]; then
    RECIPE="$(basename "$(dirname "$RUN_DIR")")"
    DEST="$ARCHIVE_DIR/$RECIPE"
    if mkdir -p "$DEST" 2>/dev/null && [[ -w "$DEST" ]]; then
        # Copy-then-remove rather than mv: /mnt/archive is a different filesystem, so mv is a
        # copy anyway, and an interrupted mv can leave a half-written bundle with no original.
        if cp -a "$RUN_DIR" "$DEST/" && [[ -f "$DEST/$RUN_ID/meta/runinfo_end.txt" ]]; then
            rm -rf "$RUN_DIR"
            for aux in "$HOME/${RUN_ID}_metrics" "$HOME/${RUN_ID}_load.csv" "$HOME/${RUN_ID}_load.log"; do
                [[ -e "$aux" ]] && cp -a "$aux" "$DEST/" 2>/dev/null && rm -rf "$aux"
            done
            MOVED="$DEST/$RUN_ID"
        else
            echo "[finish] WARN: copy to $DEST failed - leaving $RUN_ID on the collection disk"
            rm -rf "${DEST:?}/${RUN_ID:?}" 2>/dev/null || true
        fi
    else
        echo "[finish] WARN: $DEST is not writable - is /mnt/archive mounted? Leaving $RUN_ID local."
    fi
fi

echo "[finish] $RUN_ID  trace=$LOSS  -> $MOVED"
echo "$LOSS"   # last line, so a caller can capture it
