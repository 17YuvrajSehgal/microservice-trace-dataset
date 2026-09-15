#!/bin/bash
# Forced command for the Trillium pull key. See authorized_keys.
#
# WHY A FORCED COMMAND: the private half of this key lives on tri-login02, a shared multi-user
# HPC login node. An unrestricted key there would hand anyone who read it full shell on this VM.
# This key can do exactly two things: list recipe names, and stream one recipe as a tar.
set -uo pipefail
SRC=/mnt/archive/runs
cmd="${SSH_ORIGINAL_COMMAND:-}"

case "$cmd" in
    list)
        ls -1 "$SRC" 2>/dev/null
        exit 0
        ;;
    sizes)
        du -sb "$SRC"/*/ 2>/dev/null
        exit 0
        ;;
esac

# anything else must be a single bare recipe name
case "$cmd" in
    *[!a-z0-9_]*|"")
        echo "refused: expected 'list', 'sizes', or one recipe name [a-z0-9_]+" >&2
        exit 2
        ;;
esac
[ -d "$SRC/$cmd" ] || { echo "refused: no such recipe: $cmd" >&2; exit 3; }

# -1 because the kernel CTF inside is already gzipped; this only squeezes the text parts.
exec tar cf - -C "$SRC" "$cmd" 2>/dev/null | pigz -1 -p 6
