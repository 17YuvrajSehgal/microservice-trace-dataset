#!/bin/bash
# Verify a directory of per-recipe StrataTrace archives: open each one and COUNT THE RUNS INSIDE.
#
# WHY THIS IS A JOB AND NOT A LOGIN-NODE LOOP
# -------------------------------------------
# `pull_from_vm.sh --verify` does the same work inline, which is fine for a couple of archives
# and wrong for a hundred gigabytes. Measured 16 Sept 2026 on tri-login02: two verify loops over
# 107 GB, each `nice -n 19 ionice -c3`, on a node at load 48 with 57 users, were reading at
# **0.4 MB/s** - hours of wall clock for work a compute node does in minutes. SciNet's own MOTD
# asks that login nodes be kept to small test cases.
#
#   sbatch --export=DEST=/scratch/yuvraj17/stratatrace/v2/sockshop-recollected-20260915 \
#       transfer/verify_archives_job.sbatch
#   squeue --me
#
# Counting BUNDLES, not directories: every run also has a <run_id>_metrics/ sibling, so `ls -d`
# reports exactly twice the run count. `meta/runinfo_end.txt` exists once per finished run.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-verify
#SBATCH --nodes=1
#SBATCH --partition=debug
#SBATCH --time=00:55:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-verify-%j.out
set -uo pipefail

DEST="${DEST:?set DEST via --export=DEST=...}"
cd "$DEST" || exit 1
mkdir -p /scratch/yuvraj17/stratatrace/slurm-logs

echo "== verify $DEST =="
echo "   node $(hostname)  started $(date -u +%FT%TZ)"
echo

count_one() {
    local f="$1"
    local rec; rec=$(basename "$f" .tar.gz)
    local sz; sz=$(stat -c %s "$f")
    # gzip decompression is single-threaded per stream, so parallelism comes from running the
    # archives side by side rather than from threading any one of them.
    local n
    n=$(zcat "$f" 2>/dev/null | tar -tf - 2>/dev/null \
        | grep -cE "^${rec}/[^/]+/meta/runinfo_end.txt$")
    # A truncated archive still lists SOME entries, so also record whether gzip's CRC is intact.
    local crc="ok"
    gzip -t "$f" 2>/dev/null || crc="CRC FAIL"
    printf '%-30s %4s runs  %8.2f GB  %s\n' "$rec" "$n" "$(awk -v s="$sz" 'BEGIN{print s/1e9}')" "$crc"
}
export -f count_one

ls -1 "$DEST"/*.tar.gz 2>/dev/null | xargs -P 8 -I{} bash -c 'count_one "$@"' _ {} | sort

echo
echo "finished $(date -u +%FT%TZ)"
