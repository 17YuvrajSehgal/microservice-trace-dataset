#!/bin/bash
# Run this ON TRILLIUM (login node), once, before the v2 push.
#
# WHY IT HAS TO BE RUN BY A HUMAN
# -------------------------------
# Trillium accepts publickey or keyboard-interactive (MFA) and nothing else. Neither collector VM
# has a key registered here, and registering one requires a login that only the account holder can
# complete. So the two things that need a Trillium session - authorising the VMs and reading the
# quota - cannot be done from the VMs or from a laptop that is not already enrolled.
#
# It does three things and reports what it found:
#   1. authorises both v2 collector VMs to push here (idempotent - safe to re-run)
#   2. prints the /scratch quota, in bytes AND in file count
#   3. creates the v2 release root, kept separate from v1
#
#   bash trillium_setup_v2.sh
set -uo pipefail

V2_ROOT="${V2_ROOT:-/scratch/$USER/stratatrace/v2}"

# Public keys generated on the collector VMs 6 Sept 2026. Private halves never leave the VMs.
KEY_SS="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPv0AhUSXre/69PkiC+/al4dcCAR3xGlkEeTDzon8TrK strata-v2-stratatrace-ss"
KEY_TT="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGOa/15S169BYCVf70RaUU41D8I7Xtoq35U7TdjShs41 strata-v2-stratatrace-tt"

echo "=============================================================="
echo " 1. authorise the collector VMs"
echo "=============================================================="
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
for k in "$KEY_SS" "$KEY_TT"; do
    tag="${k##* }"
    # Match on the key body, not the comment - a re-run with a changed comment must not add a
    # second copy of the same key.
    body="$(echo "$k" | awk '{print $2}')"
    if grep -qF "$body" ~/.ssh/authorized_keys; then
        echo "  already authorised: $tag"
    else
        echo "$k" >> ~/.ssh/authorized_keys
        echo "  ADDED: $tag"
    fi
done

echo
echo "=============================================================="
echo " 2. quota - the push is 1.18 TB and ~303 bundles"
echo "=============================================================="
echo "-- diskusage_report --"
diskusage_report 2>/dev/null || echo "  (diskusage_report not available)"
echo
echo "-- filesystem free space --"
df -h /scratch/"$USER" 2>/dev/null || df -h /scratch 2>/dev/null || true
echo
echo "-- what v1 already occupies --"
du -sh /scratch/"$USER"/stratatrace 2>/dev/null || echo "  (no stratatrace dir yet)"

echo
echo "=============================================================="
echo " 3. create the v2 release root"
echo "=============================================================="
# Separate from v1. v2 reuses every v1 recipe name, so sharing a root would let one release's
# tarballs overwrite the other's with no way to tell them apart afterwards.
mkdir -p "$V2_ROOT/sockshop" "$V2_ROOT/trainticket"
ls -ld "$V2_ROOT" "$V2_ROOT"/*
echo
echo "V2_ROOT=$V2_ROOT"
echo
echo "Done. Report the quota numbers back, then the push can start:"
echo "  DEST_ROOT=$V2_ROOT SRC=/mnt/archive/runs APP=sockshop    bash push_to_trillium.sh"
echo "  DEST_ROOT=$V2_ROOT SRC=/mnt/archive/runs APP=trainticket bash push_to_trillium.sh"
