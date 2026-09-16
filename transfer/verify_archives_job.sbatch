#!/bin/bash
# Verify a directory of per-recipe StrataTrace archives: open each one and COUNT THE RUNS INSIDE.
#
# WHY THIS IS A JOB AND NOT A LOGIN-NODE LOOP
# -------------------------------------------
# `pull_from_vm.sh --verify` does the same work inline, which is fine for a couple of archives
# and wrong for a hundred gigabytes. Measured 16 Sept 2026 on tri-login02: two verify loops over
# 107 GB, each `nice -n 19 ionice -c3`, on a node at load 48 with 57 users, were reading at
# **0.4 MB/s**. SciNet's MOTD asks that login nodes be kept to small test cases.
#
#   sbatch --export=DEST=/scratch/.../sockshop-recollected-20260915 \
#       transfer/verify_archives_job.sbatch
#   sbatch --export=DEST=...,ONLY="code_n_plus_one dns_delay" ...   # subset
#
# THREE THINGS THE FIRST VERSION GOT WRONG (job 2320736, killed at the 55-minute wall clock
# with ZERO output - all three were mine):
#
#   1. It read every archive TWICE: once for `zcat | tar -tf` to count runs, again for
#      `gzip -t` to check the CRC. 214 GB of reads for 107 GB of data. Now ONE pass -
#      zcat's own exit status already reports a CRC failure, so PIPESTATUS gives the same
#      guarantee for free.
#   2. It piped xargs through `sort`, which buffers until the LAST archive finishes. When the
#      job hit the wall clock nothing had been written at all. Now each archive prints as it
#      completes, so a job that dies early still leaves partial results.
#   3. It used the `debug` partition (55 min). The work is I/O bound on /scratch - that job
#      burned 55 minutes of wall clock for 3 minutes of CPU on 192 cores - so it needs the
#      `compute` partition's headroom, not more cores.
#
# Counting BUNDLES, not directories: every run also has a <run_id>_metrics/ sibling, so `ls -d`
# reports exactly twice the run count. `meta/runinfo_end.txt` exists once per finished run.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-verify
#SBATCH --nodes=1
#SBATCH --time=03:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-verify-%j.out
set -uo pipefail

DEST="${DEST:?set DEST via --export=DEST=...}"
ONLY="${ONLY:-}"          # optional space-separated recipe names; default is every archive
PAR="${PAR:-4}"           # I/O bound, so more streams stop helping quickly

mkdir -p /scratch/yuvraj17/stratatrace/slurm-logs
echo "== verify $DEST"
echo "   node $(hostname)  par=$PAR  started $(date -u +%FT%TZ)"
echo

count_one() {
    local f="$1"
    local rec; rec=$(basename "$f" .tar.gz)
    local sz; sz=$(stat -c %s "$f")
    local n
    # ONE read. PIPESTATUS[0] is zcat's status: non-zero means a CRC or truncation error, which
    # is exactly what the separate `gzip -t` pass used to cost a second full read to learn.
    n=$(zcat "$f" 2>/dev/null | tar -tf - 2>/dev/null \
        | grep -cE "^${rec}/[^/]+/meta/runinfo_end.txt$")
    local zrc=${PIPESTATUS[0]}
    local health="ok"
    [ "$zrc" -ne 0 ] && health="DECOMPRESS FAIL (zcat rc=$zrc)"
    printf '%-30s %4s runs  %8.2f GB  %s\n' \
        "$rec" "$n" "$(awk -v s="$sz" 'BEGIN{print s/1e9}')" "$health"
}
export -f count_one

if [ -n "$ONLY" ]; then
    for r in $ONLY; do echo "$DEST/$r.tar.gz"; done
else
    ls -1 "$DEST"/*.tar.gz 2>/dev/null
fi | xargs -P "$PAR" -I{} bash -c 'count_one "$@"' _ {}

echo
echo "finished $(date -u +%FT%TZ)"
