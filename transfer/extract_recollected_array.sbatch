#!/bin/bash
# Extract the RE-COLLECTED archives into the working copy, one archive per array task.
#
# WHY THIS EXISTS
# ---------------
# `v2/*-recollected-*/` holds the archives; `data/stratatrace-v2/<app>/<recipe>/<run>/` is the
# working copy that every analysis actually reads. Those are different things, and on 16-17 Sept
# they fell out of step: the superseded Sock Shop trees were retired from the working copy and
# the 54 replacements were never extracted into it. Sock Shop read 116 runs where it should read
# 170, missing ten whole families - and nothing complains, the families are simply absent.
#
#   sbatch --array=0-11 transfer/extract_recollected_array.sbatch     # sockshop set
#   APP=trainticket SRC=... sbatch --array=0-2 ...                    # edit the two vars below
#
# Provenance archives are skipped: they are not run bundles and do not belong in the working
# copy. They stay as archives.
#
# Resumable: a recipe whose directory already holds the expected run count is left alone.
#SBATCH --account=def-naser2
#SBATCH --job-name=strata-extract
#SBATCH --nodes=1
#SBATCH --time=02:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/strata-extract-%A_%a.out
set -uo pipefail

R=/scratch/yuvraj17/stratatrace
SRC=${SRC:-$R/v2/sockshop-recollected-20260915}
APP=${APP:-sockshop}
DEST=$R/data/stratatrace-v2/$APP
mkdir -p "$DEST" "$R/slurm-logs"

mapfile -t FILES < <(ls -1 "$SRC"/*.tar.gz 2>/dev/null | grep -v '/provenance' | sort)
i="${SLURM_ARRAY_TASK_ID:-0}"
f="${FILES[$i]:-}"
[ -n "$f" ] || { echo "task $i: no archive at that index (have ${#FILES[@]})"; exit 0; }
rec=$(basename "$f" .tar.gz)

echo "task $i  $rec -> $DEST  node $(hostname)  $(date -u +%FT%TZ)"

# how many runs the archive claims, so we can tell "already done" from "half done"
want=$(zcat "$f" 2>/dev/null | tar -tf - 2>/dev/null \
       | grep -cE "^${rec}/[^/]+/meta/runinfo_end.txt$")
have=0
for d in "$DEST/$rec"/*/; do
    case "$d" in *_metrics/) continue;; esac
    [ -f "$d/meta/runinfo_end.txt" ] && have=$((have + 1))
done
echo "  archive holds $want run(s); working copy already has $have"
if [ "$want" -gt 0 ] && [ "$have" -eq "$want" ]; then
    echo "  already extracted, nothing to do"
    exit 0
fi

zcat "$f" 2>/dev/null | tar -xf - -C "$DEST" 2>/dev/null
zrc=${PIPESTATUS[0]}
[ "$zrc" -ne 0 ] && { echo "  DECOMPRESS FAIL rc=$zrc"; exit 1; }

# The working copy is kept fully decompressed - no .gz anywhere - so a reader never needs a
# decode step. The archives ship CTF streams gzipped, so undo that here.
find "$DEST/$rec" -name '*.gz' -exec gunzip -q {} + 2>/dev/null

got=0
for d in "$DEST/$rec"/*/; do
    case "$d" in *_metrics/) continue;; esac
    [ -f "$d/meta/runinfo_end.txt" ] && got=$((got + 1))
done
printf '  %-28s %s runs extracted, %s remaining .gz\n' "$rec" "$got" \
    "$(find "$DEST/$rec" -name '*.gz' 2>/dev/null | wc -l)"
echo "done $(date -u +%FT%TZ)"
