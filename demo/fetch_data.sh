#!/usr/bin/env bash
# Fetch the one trace the demo runs on. ~37 MB.
#
# This is the INDEX, not the raw trace: the raw CTF for this run is 15 GB, and the index is
# what the agent's tools actually read. Counts per 100 ms bucket per (event, process,
# container), plus one raw event line per bucket. Built by a single decode of the full trace.
set -eu
RUN=svc_net_aggressive_steady_r3
SRC=trillium:/scratch/yuvraj17/stratatrace
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/data"
rsync -a --info=progress2 \
  "$SRC/dataset/index-v2/$RUN.tsv.gz" \
  "$SRC/dataset/index-v2/$RUN.lines.gz" \
  "$SRC/dataset/runs/sockshop/svc_net/$RUN/ground_truth.json" \
  "$HERE/data/"
echo
echo "fetched into $HERE/data:"
ls -la "$HERE/data"
