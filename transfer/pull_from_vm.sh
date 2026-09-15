#!/bin/bash
# pull_from_vm.sh - pull StrataTrace runs from a GCP collector VM, running ON TRILLIUM.
#
# WHY THIS EXISTS (and why push_to_trillium.sh is no longer enough)
# ----------------------------------------------------------------
# push_to_trillium.sh runs on the VM and needs key-based SSH from the VM to Trillium. That
# stopped working. Alliance now requires a second factor even when a CCDB-registered key passes:
#
#     debug1: Server accepts key: ... ED25519 SHA256:Zexa...B78
#     Authenticated using "publickey" with partial success.
#     debug1: Authentications that can continue: keyboard-interactive,hostbased
#
# "Partial success" means the key was fine and Duo still wants a passcode. A batch-mode push
# cannot answer that, so the direction is inverted: Trillium dials the VM instead. Measured
# 15 Sept 2026 - tri-login02 CAN open port 22 outbound to the VM's external address.
#
#   ssh trillium                 # your normal MFA login, once
#   VM_HOST=<ip> DEST=/scratch/yuvraj17/stratatrace/v2/sockshop ./pull_from_vm.sh
#   ./pull_from_vm.sh --verify   # tar-test every archive and count runs
#
# THE KEY ON THE VM IS DELIBERATELY RESTRICTED. Its private half lives on a shared multi-user
# login node, so an unrestricted key there would be a shell on the VM for anyone who read it.
# The VM's authorized_keys binds it to a forced command that accepts only `list`, `sizes`, or
# one recipe name, and streams that recipe as tar|pigz. See faults/../bin/export_recipe.sh.
#
# NOTE the VM's external IP is EPHEMERAL - it changes every time the instance is stopped and
# started. Always pass the current one:
#   gcloud compute instances describe stratatrace-ss --zone=us-east1-d \
#       --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
set -uo pipefail

VM_USER="${VM_USER:-17yuv}"
VM_HOST="${VM_HOST:?set VM_HOST to the collector VM external IP (it is ephemeral - re-read it after every restart)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ss_vm}"
PAR="${PAR:-4}"
DEST="${DEST:?set DEST, e.g. /scratch/yuvraj17/stratatrace/v2/sockshop}"

SSH="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=10"
REMOTE="$VM_USER@$VM_HOST"

# The forced command answers `list`; that is also the connectivity test.
mapfile -t RECIPES < <($SSH "$REMOTE" list 2>/dev/null | grep -vE '_metrics$' | grep -E '^[a-z0-9_]+$')
[ "${#RECIPES[@]}" -gt 0 ] || {
    echo "FATAL: could not list recipes on $REMOTE."
    echo "  - is the key authorized there?  ssh -i $SSH_KEY $REMOTE list"
    echo "  - has the VM restarted and changed its ephemeral IP?"
    exit 1
}

if [ "${1:-}" = "--verify" ]; then
    echo "== verify $DEST =="
    rc=0
    for rec in "${RECIPES[@]}"; do
        f="$DEST/$rec.tar.gz"
        [ -f "$f" ] || { printf '  %-28s MISSING\n' "$rec"; rc=1; continue; }
        # Count bundles by a file every finished run has. Counting directories double-counts:
        # each run also has a <run_id>_metrics/ sibling.
        n=$(nice -n 19 ionice -c3 sh -c "zcat '$f' 2>/dev/null | tar -tf - 2>/dev/null \
            | grep -cE '^$rec/[^/]+/meta/runinfo_end.txt\$'" 2>/dev/null || echo ERR)
        sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
        printf '  %-28s %6s runs  %8.2f GB\n' "$rec" "$n" "$(echo "$sz" | awk '{print $1/1e9}')"
        [ "$n" = "0" ] || [ "$n" = "ERR" ] && rc=1
    done
    exit $rc
fi

mkdir -p "$DEST" || exit 1
echo "== pulling ${#RECIPES[@]} recipes from $REMOTE -> $DEST ($PAR parallel) =="

pull_recipe() {
    local rec="$1"
    local out="$DEST/$rec.tar.gz"
    # Resumable: a finished archive is left alone. A .partial is always re-fetched, because a
    # truncated stream is worse than no archive - it looks like data.
    local sz; sz=$(stat -c %s "$out" 2>/dev/null || echo 0)
    if [ "${sz:-0}" -gt 1000000 ]; then
        echo "SKIP $rec (exists, $((sz / 1000000)) MB)"
        return 0
    fi
    if $SSH "$REMOTE" "$rec" > "$out.partial" 2>/dev/null && [ -s "$out.partial" ]; then
        mv "$out.partial" "$out"
        echo "OK   $rec ($(( $(stat -c %s "$out") / 1000000 )) MB)"
    else
        echo "FAIL $rec"
        rm -f "$out.partial"
        return 1
    fi
}
export -f pull_recipe
export SSH REMOTE DEST

printf '%s\n' "${RECIPES[@]}" | xargs -P "$PAR" -I{} bash -c 'pull_recipe "$@"' _ {}

echo
echo "== done. verify with: $0 --verify =="
