#!/bin/bash
# Verify per-recipe StrataTrace archives - ONE ARCHIVE PER ARRAY TASK, so each gets its own node.
#
#   sbatch --array=0-9 transfer/verify_archives_array.sbatch
#   (DEST is baked in below because --export does not survive Trillium's sbatch wrapper.)
#
# WHY AN ARRAY, after three single-node jobs were killed at their wall clock
# -------------------------------------------------------------------------
# Jobs 2320736, 2321025/2321061 and 2321160 all died at the limit having verified only part of
# the set. 2321160 ran the full three hours and burned SEVEN MINUTES of CPU - 4% busy. The work
# is not CPU bound and it is not helped by the 192 cores a whole node gives you: it is bound by
# how fast ONE node can pull gzip streams off /scratch, and running four archives side by side
# on that one node just splits the same pipe four ways.
#
# An array fixes the actual constraint. Ten tasks land on ten nodes, each reading one archive
# through its own path, and the slowest task is one archive rather than the whole directory.
#
# RESUMABLE. A verified archive gets a `.verified` marker beside it, and a task that finds one
# exits immediately - so a re-submit only re-reads what is still in doubt, and a task killed at
# the wall clock costs one archive rather than the run.
#
# Counting BUNDLES, not directories: every run also has a <run_id>_metrics/ sibling, so `ls -d`
# reports exactly twice the run count. `meta/runinfo_end.txt` exists once per finished run.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-vrfy
#SBATCH --nodes=1
#SBATCH --time=01:30:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-vrfy-%A_%a.out
set -uo pipefail

DEST=/scratch/yuvraj17/stratatrace/v2/sockshop-recollected-20260915
mkdir -p /scratch/yuvraj17/stratatrace/slurm-logs

mapfile -t FILES < <(ls -1 "$DEST"/*.tar.gz 2>/dev/null | sort)
i="${SLURM_ARRAY_TASK_ID:-0}"
f="${FILES[$i]:-}"
[ -n "$f" ] || { echo "task $i: no archive at that index (have ${#FILES[@]})"; exit 0; }

rec=$(basename "$f" .tar.gz)
echo "task $i  $rec  node $(hostname)  started $(date -u +%FT%TZ)"

if [ -f "$f.verified" ]; then
    echo "$rec already verified: $(cat "$f.verified")"
    exit 0
fi

sz=$(stat -c %s "$f")
t0=$(date +%s)
# ONE read. PIPESTATUS[0] is zcat's status - non-zero means CRC or truncation, which is exactly
# what a separate `gzip -t` pass would cost a second full read to learn.
n=$(zcat "$f" 2>/dev/null | tar -tf - 2>/dev/null \
    | grep -cE "^${rec}/[^/]+/meta/runinfo_end.txt$")
zrc=${PIPESTATUS[0]}
t1=$(date +%s)

line=$(printf '%-30s %4s runs  %8.2f GB  %s  (%ds, %.0f MB/s)' \
    "$rec" "$n" "$(awk -v s="$sz" 'BEGIN{print s/1e9}')" \
    "$([ "$zrc" -eq 0 ] && echo ok || echo "DECOMPRESS FAIL rc=$zrc")" \
    "$((t1 - t0))" "$(awk -v s="$sz" -v d="$((t1 - t0))" 'BEGIN{print (d>0)?s/d/1e6:0}')")
echo "$line"

# Only mark archives that actually passed; a failure must stay in doubt for the next submit.
if [ "$zrc" -eq 0 ] && [ "${n:-0}" -gt 0 ]; then
    echo "$line" > "$f.verified"
fi
