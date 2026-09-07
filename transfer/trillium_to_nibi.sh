#!/bin/bash
# Copy a StrataTrace release from Trillium to Nibi, for a second copy on independent hardware.
#
# RUNS ON TRILLIUM. The Trillium -> Nibi hop authenticates with your FORWARDED ssh agent, which is
# why the session you launch this from must be opened with `ssh -A`.
#
#   bash trillium_to_nibi.sh --check      # reachability + quota on both ends, transfers nothing
#   bash trillium_to_nibi.sh              # do the copy (backgrounded, logged, resumable)
#   bash trillium_to_nibi.sh --verify     # compare file count and bytes end to end
#
#   env: SRC (default /scratch/$USER/stratatrace/v2)  DEST (default same path on Nibi)
#
# WHY NOT `rsync -avzh` LIKE LAST TIME
# ------------------------------------
# `-z` compresses in flight. The v1 copy was a text dump, so it paid off. This release is 51
# gzip files - already compressed - so `-z` spends CPU to produce output no smaller, and on a
# fast link it becomes the bottleneck rather than the network. Dropped, and a fast AES-NI cipher
# used instead.
#
# Globus is the Alliance's recommended tool for cluster-to-cluster moves and handles restart and
# checksum verification for you. rsync is used here because it needs no endpoint setup and the
# payload is 51 large files, which is the case rsync handles well.
set -uo pipefail

SRC="${SRC:-/scratch/$USER/stratatrace/v2}"
DEST="${DEST:-/scratch/$USER/stratatrace/v2}"
NIBI="${NIBI:-$USER@nibi.alliancecan.ca}"
LOG="${LOG:-$HOME/trillium_to_nibi.log}"
# No compression (payload is gzip), fast cipher, keep the connection alive through long file
# transfers where the control channel would otherwise look idle.
RSH="${RSH:-ssh -o Compression=no -c aes128-gcm@openssh.com -o ServerAliveInterval=30 -o ServerAliveCountMax=10}"

say() { printf '%s\n' "$*"; }

[[ -d "$SRC" ]] || { say "FATAL: no such source dir: $SRC"; exit 1; }

if [[ "${1:-}" == "--check" ]]; then
    say "=============================================================="
    say " source on Trillium: $SRC"
    say "=============================================================="
    du -sh "$SRC" 2>/dev/null
    say "  files: $(find "$SRC" -type f | wc -l)"
    find "$SRC" -mindepth 1 -maxdepth 1 -type d -printf '  %p\n'
    say
    say "=============================================================="
    say " can Trillium reach Nibi? (needs the forwarded agent)"
    say "=============================================================="
    if timeout 30 $RSH -o BatchMode=yes "$NIBI" "echo REACHED on \$(hostname)" 2>&1 | tail -2; then :; fi
    say
    say "=============================================================="
    say " Nibi quota - /project is backed up, /scratch is not"
    say "=============================================================="
    timeout 60 $RSH -o BatchMode=yes "$NIBI" "diskusage_report 2>/dev/null || echo '(diskusage_report unavailable)'"
    exit 0
fi

if [[ "${1:-}" == "--verify" ]]; then
    say "== comparing $SRC (Trillium) with $DEST (Nibi) =="
    l_files=$(find "$SRC" -type f | wc -l)
    l_bytes=$(du -sb "$SRC" | cut -f1)
    r=$(timeout 120 $RSH -o BatchMode=yes "$NIBI" "find '$DEST' -type f 2>/dev/null | wc -l; du -sb '$DEST' 2>/dev/null | cut -f1")
    r_files=$(echo "$r" | sed -n 1p); r_bytes=$(echo "$r" | sed -n 2p)
    printf '  files  Trillium=%s  Nibi=%s  %s\n' "$l_files" "$r_files" \
        "$([[ "$l_files" == "$r_files" ]] && echo OK || echo MISMATCH)"
    printf '  bytes  Trillium=%s  Nibi=%s  %s\n' "$l_bytes" "$r_bytes" \
        "$([[ "$l_bytes" == "$r_bytes" ]] && echo OK || echo MISMATCH)"
    say
    say "  (byte-identical is the real check here - every file is a gzip archive, so any"
    say "   truncation changes the size. For a content check, gzip -t each file on Nibi.)"
    exit 0
fi

# ---- the copy ---------------------------------------------------------------------------------
say "== $SRC  ->  $NIBI:$DEST =="
say "   log: $LOG   (resumable: re-run and rsync skips what already matches)"
timeout 30 $RSH -o BatchMode=yes "$NIBI" "mkdir -p '$DEST'" || {
    say "FATAL: cannot reach Nibi or create $DEST."
    say "  Did you open this Trillium session with 'ssh -A' and have the key in a local agent?"
    say "  Test:  $RSH $NIBI hostname"
    exit 1
}

# nice/ionice: this runs on a shared login node.
setsid nohup nice -n 19 ionice -c3 rsync -ah --info=progress2 --partial \
    -e "$RSH" "$SRC/" "$NIBI:$DEST/" > "$LOG" 2>&1 < /dev/null &
sleep 5
say "started (pid $(pgrep -f 'rsync -ah --info=progress2' | head -1))"
say "watch:   tail -f $LOG"
say "verify:  bash $0 --verify"
