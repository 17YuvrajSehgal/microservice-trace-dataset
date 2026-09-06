#!/bin/bash
# push_to_trillium.sh — fast, organized, compressed push of a StrataTrace dataset from a GCP
# collector VM to Trillium (SciNet /scratch). Design (see transfer/README.md):
#   * per-RECIPE tar.gz archives (one file per fault family) - tiny /scratch inode footprint and
#     unambiguous extraction (each archive = one recipe's runs, nothing can mix)
#   * STREAMED over ssh and written on Trillium -> no local scratch space needed
#   * pigz (parallel gzip) compresses the text; the already-gz kernel CTF passes straight through
#   * parallel across recipes + a fast AES-NI cipher to fill the WAN pipe
#   * atomic (.partial -> mv) and resumable (skip archives that already exist)
#
#   v2 (runs live on the archive disk, one dir per recipe):
#     DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=sockshop    ./push_to_trillium.sh
#     DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=trainticket ./push_to_trillium.sh
#   v1 kept its runs in $HOME/traces; the layout below $SRC is the same either way.
#   ./push_to_trillium.sh --verify        # after a run: tar-test every remote archive + count runs
#
# Needs key-based SSH from THIS VM to Trillium. Test first:
#   ssh ${SSH_KEY:+-i $SSH_KEY} $TRILLIUM_USER@trillium.scinet.utoronto.ca hostname
set -uo pipefail
TRILLIUM_USER="${TRILLIUM_USER:-yuvraj17}"
TRILLIUM_HOST="${TRILLIUM_HOST:-trillium.scinet.utoronto.ca}"
# DELIBERATELY HAS NO DEFAULT. It used to default to /scratch/yuvraj17/stratatrace/repo, which
# is where the v1 release already lives (CLUSTER-LAYOUT.md). v2 has the same recipe names, so a
# default push would have written v2 tarballs over v1's with no warning and no way to tell which
# release a file came from. Name the release you are pushing.
DEST_ROOT="${DEST_ROOT:?set DEST_ROOT to the release root, e.g. /scratch/yuvraj17/stratatrace/v2 (v1 occupies /scratch/yuvraj17/stratatrace/repo - do not push v2 there)}"
PAR="${PAR:-4}"                 # parallel recipe streams (each fills one WAN connection)
PIGZ_P="${PIGZ_P:-4}"           # cores per pigz worker (PAR*PIGZ_P <= vCPUs)
# default to the per-VM transfer key if present (SciNet/Alliance = key + MFA); override with SSH_KEY=
SSH_KEY="${SSH_KEY:-$HOME/.ssh/trillium}"; [ -f "$SSH_KEY" ] || SSH_KEY=""
REMOTE="$TRILLIUM_USER@$TRILLIUM_HOST"
# Both clusters mandate MFA, so we multiplex over ONE interactively-authenticated master
# connection: every push stream reuses it, no re-auth. Establish the master ONCE (interactive,
# does the MFA), then run the push:
#   ssh -fNM -o ControlPath=$HOME/.ssh/cm-strata-<host> -o ControlPersist=12h [-i key] user@host
CM_PATH="${CM_PATH:-$HOME/.ssh/cm-strata-$TRILLIUM_HOST}"
# fast, AES-NI cipher; ssh-level compression off (pigz compresses); reuse the master, never prompt
SSH="ssh -o Compression=no -c aes128-gcm@openssh.com -o ControlMaster=no -o ControlPath=$CM_PATH -o BatchMode=yes ${SSH_KEY:+-i $SSH_KEY}"

if [ "${1:-}" = "--setup-master" ]; then
  echo "== opening MFA'd master to $REMOTE (persists 12h; do the MFA when prompted) =="
  exec ssh -fNM -o ControlPath=$CM_PATH -o ControlPersist=12h -o StrictHostKeyChecking=accept-new ${SSH_KEY:+-i $SSH_KEY} "$REMOTE"
fi
if ! ssh -o ControlPath=$CM_PATH -O check "$REMOTE" 2>/dev/null; then
  echo "No live master to $REMOTE. First (interactively, once - does the MFA):"
  echo "   bash $0 --setup-master        # or: ssh -fNM -o ControlPath=$CM_PATH -o ControlPersist=12h ${SSH_KEY:+-i $SSH_KEY} $REMOTE"
  echo "Then re-run the push."; exit 1
fi
# from here on we actually push, so require SRC/APP
SRC="${SRC:?set SRC to the traces dir (e.g. /mnt/data/traces or \$HOME/traces)}"
APP="${APP:?set APP to sockshop|trainticket}"
DEST="$DEST_ROOT/$APP"
COMP="${COMP:-pigz -p $PIGZ_P}"; command -v pigz >/dev/null 2>&1 || { COMP="gzip"; echo "(pigz not found -> gzip; 'sudo apt-get install -y pigz' for parallel speed)"; }

$SSH "$REMOTE" "mkdir -p '$DEST'" || { echo "FATAL: master to $REMOTE not usable"; exit 1; }
mapfile -t RECIPES < <(cd "$SRC" && ls -d */ 2>/dev/null | sed 's#/##')
[ "${#RECIPES[@]}" -gt 0 ] || { echo "FATAL: no recipe dirs under $SRC"; exit 1; }

# ---- verify mode: tar-test every remote archive + report run counts -------------------------
if [ "${1:-}" = "--verify" ]; then
  echo "== verify $APP archives on $REMOTE:$DEST =="
  for rec in "${RECIPES[@]}"; do
    # Count BUNDLES, not directories. Each recipe dir also holds a <run_id>_metrics/ aux dir per
    # run, so `ls -d */` reports exactly twice the run count and every recipe reads MISMATCH.
    local_runs=$(find "$SRC/$rec" -mindepth 2 -maxdepth 3 -path "*/meta/runinfo_end.txt" 2>/dev/null | wc -l)
    remote_runs=$($SSH "$REMOTE" "zcat '$DEST/${rec}.tar.gz' 2>/dev/null | tar -tf - 2>/dev/null | grep -cE '^${rec}/[^/]+/meta/runinfo_end.txt$'" 2>/dev/null || echo ERR)
    ok="OK "; [ "$local_runs" = "$remote_runs" ] || ok="MISMATCH"; echo "  $ok $rec: local=$local_runs remote=$remote_runs"
  done
  exit 0
fi

# ---- push ------------------------------------------------------------------------------------
echo "== $APP: ${#RECIPES[@]} recipes, $PAR parallel streams, compressor='$COMP' -> $REMOTE:$DEST =="
push_recipe() {
  local rec="$1"; local out="$DEST/${rec}.tar.gz"
  local sz; sz=$($SSH "$REMOTE" "stat -c%s '$out' 2>/dev/null || echo 0")
  if [ "${sz:-0}" -gt 1000000 ]; then echo "SKIP $rec (exists, $((sz/1000000)) MB)"; return; fi
  local t0; t0=$(date +%s)
  if tar cf - -C "$SRC" "$rec" | $COMP | $SSH "$REMOTE" "cat > '$out.partial' && mv '$out.partial' '$out'"; then
    local rsz; rsz=$($SSH "$REMOTE" "stat -c%s '$out' 2>/dev/null || echo 0")
    echo "OK   $rec ($(( $(date +%s)-t0 ))s, $((rsz/1000000)) MB)"
  else
    echo "FAIL $rec"; $SSH "$REMOTE" "rm -f '$out.partial'" 2>/dev/null
  fi
}
export -f push_recipe; export SRC DEST REMOTE SSH COMP
printf '%s\n' "${RECIPES[@]}" | xargs -P "$PAR" -I{} bash -c 'push_recipe "$@"' _ {}

# aux: per-run Prometheus metrics + client load CSVs.
#
# In v1 these sat loose in $HOME and needed their own archive. Since v2, campaign_finish_run.sh
# moves them next to the bundle, INSIDE $SRC/<recipe>/ - so the per-recipe tar above already
# carries them and no separate _aux archive is produced. The $HOME sweep stays only to catch a
# run finished before that change.
AUX=$(cd "$HOME" && ls -d *_metrics *_load.csv 2>/dev/null)
if [ -n "$AUX" ]; then
  echo "== aux left in \$HOME (pre-archive-move runs) =="
  tar cf - -C "$HOME" $AUX 2>/dev/null | $COMP | $SSH "$REMOTE" "cat > '$DEST/_aux_metrics_load.tar.gz.partial' && mv '$DEST/_aux_metrics_load.tar.gz.partial' '$DEST/_aux_metrics_load.tar.gz'" && echo "OK aux"
else
  echo "== aux travels inside the per-recipe archives (nothing loose in \$HOME) =="
fi

# The Prometheus TSDB snapshot is NOT under $SRC, so nothing above would have carried it. It is
# the continuous record - the gaps between runs and the cross-run baselines that the per-run
# exports cannot reconstruct - and it is what the outstanding verdicts get re-scored against.
PROM_SNAP="${PROM_SNAP:-/mnt/archive/prometheus}"
if [ -d "$PROM_SNAP" ]; then
  echo "== prometheus snapshot =="
  tar cf - -C "$(dirname "$PROM_SNAP")" "$(basename "$PROM_SNAP")" 2>/dev/null | $COMP     | $SSH "$REMOTE" "cat > '$DEST/_prometheus_snapshot.tar.gz.partial' && mv '$DEST/_prometheus_snapshot.tar.gz.partial' '$DEST/_prometheus_snapshot.tar.gz'"     && echo "OK prometheus"
fi
# ship the dataset manifest too if present
[ -f "$HOME/tt_dataset_manifest.csv" ] && $SSH "$REMOTE" "cat > '$DEST/manifest.csv'" < "$HOME/tt_dataset_manifest.csv" && echo "OK manifest"
echo "== DONE $APP. Verify:  ./push_to_trillium.sh --verify   (then extract on Trillium: transfer/extract_on_trillium.sh) =="
