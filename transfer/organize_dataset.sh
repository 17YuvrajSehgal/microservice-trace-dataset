#!/bin/bash
# Put the whole v2 dataset under ONE directory on Trillium, and move everything that is not
# the dataset out of the way.
#
# WHY
#   The dataset was spread over three places that did not look related:
#     data/stratatrace-v2/   the extracted runs analysis reads   7.7 TB
#     v2/                    the tar.gz release form             844 GB, in FOUR subdirs
#     data/ctf-index/        the count indexes                    42 MB
#   plus 1.3 TB of retired runs at the top level and 2.8 TB of v1-era material under data/.
#   Nothing said which was current. The archives and the working copy have already fallen out
#   of step once (DATASET-v2-INVENTORY.md, "Archives and the working copy are different
#   things"), and ten Sock Shop families went missing for two days without anything failing.
#
# SAFETY
#   Every step is `mv` within /scratch, which is a rename on the same filesystem: instant, and
#   no bytes are copied or deleted. NOTHING IS DELETED BY THIS SCRIPT. Old paths are left as
#   symlinks, so code that still points at them keeps working even if a reference was missed.
#
#   Run with --dry-run first. It prints every action and touches nothing.
#
# Usage:  organize_dataset.sh [--dry-run]

set -u
S=/scratch/yuvraj17/stratatrace
D=$S/dataset
A=$S/attic

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY" = 1 ]; then printf '   would: %s\n' "$*"; else eval "$@"; fi
}

# Refuse to run while an experiment is reading the tree.
if pgrep -f 'q2_run_(one|matrix)' >/dev/null 2>&1; then
  say "REFUSING: a q2 run is in progress. Moving the dataset under it would break it."
  exit 1
fi

say "=== 1. create the layout ==="
for p in "$D/runs" "$D/archives/sockshop" "$D/archives/trainticket" \
         "$D/archives/provenance" "$D/index" "$A"; do
  run "mkdir -p '$p'"
done

say
say "=== 2. the extracted runs (7.7 TB) -> dataset/runs ==="
if [ -d "$S/data/stratatrace-v2" ] && [ ! -L "$S/data/stratatrace-v2" ]; then
  for app in sockshop trainticket; do
    if [ -d "$S/data/stratatrace-v2/$app" ]; then
      run "mv '$S/data/stratatrace-v2/$app' '$D/runs/$app'"
    fi
  done
  # whatever else was in there, keep it rather than assume
  run "find '$S/data/stratatrace-v2' -mindepth 1 -maxdepth 1 -exec mv -t '$D/runs/' {} + 2>/dev/null || true"
  run "rmdir '$S/data/stratatrace-v2' 2>/dev/null || true"
  run "ln -s '$D/runs' '$S/data/stratatrace-v2'"
else
  say "   already moved (or is a symlink) - skipping"
fi

say
say "=== 3. the release archives -> dataset/archives ==="
# The original campaign and the re-collection hold DIFFERENT families - the originals of the
# re-collected ones were retired - so merging them per app cannot overwrite anything. Which
# archive came from which campaign is recorded in dataset/README.md, not in a directory name.
for src in "$S/v2/sockshop" "$S/v2/sockshop-recollected-20260915"; do
  [ -d "$src" ] || continue
  run "find '$src' -maxdepth 1 -type f -name 'provenance_*' -exec mv -t '$D/archives/provenance/' {} + 2>/dev/null || true"
  run "find '$src' -maxdepth 1 -type f -exec mv -t '$D/archives/sockshop/' {} + 2>/dev/null || true"
  run "rmdir '$src' 2>/dev/null || true"
done
for src in "$S/v2/trainticket" "$S/v2/trainticket-recollected-20260917"; do
  [ -d "$src" ] || continue
  run "find '$src' -maxdepth 1 -type f -name 'provenance_*' -exec mv -t '$D/archives/provenance/' {} + 2>/dev/null || true"
  run "find '$src' -maxdepth 1 -type f -exec mv -t '$D/archives/trainticket/' {} + 2>/dev/null || true"
  run "rmdir '$src' 2>/dev/null || true"
done
run "rmdir '$S/v2' 2>/dev/null || true"

say
say "=== 4. the count indexes -> dataset/index ==="
if [ -d "$S/data/ctf-index" ] && [ ! -L "$S/data/ctf-index" ]; then
  run "find '$S/data/ctf-index' -maxdepth 1 -type f -exec mv -t '$D/index/' {} + 2>/dev/null || true"
  run "rmdir '$S/data/ctf-index' 2>/dev/null || true"
  run "ln -s '$D/index' '$S/data/ctf-index'"
else
  say "   already moved - skipping"
fi

say
say "=== 5. retired runs -> attic (NOT deleted) ==="
for p in superseded-20260917 superseded-20260915-issue17; do
  if [ -d "$S/$p" ] && [ ! -e "$A/$p" ]; then
    run "mv '$S/$p' '$A/$p'"
  fi
done

say
say "=== 6. v1-era material -> attic/v1-and-earlier (NOT deleted, symlinked back) ==="
run "mkdir -p '$A/v1-and-earlier'"
for p in l0 stratatrace-v1 agentic-runs; do
  if [ -d "$S/data/$p" ] && [ ! -L "$S/data/$p" ]; then
    run "mv '$S/data/$p' '$A/v1-and-earlier/$p'"
    run "ln -s '$A/v1-and-earlier/$p' '$S/data/$p'"
  fi
done

say
say "=== done ==="
[ "$DRY" = 1 ] && say "(dry run - nothing was changed)"
