#!/bin/bash
# Fault recipe: a service's name resolves to the wrong address for one caller.
#
# The front-end's hosts file gets an entry that maps the catalogue's name to an address where
# nothing answers. The name lookup works (and is fast); every new connection from the front-end
# to "catalogue" then goes to the wrong place and waits for an answer that never comes, until it
# times out. The catalogue itself is healthy and other callers are not affected.
#
# WHY THIS FAMILY. dependency_outage stops the callee; dns_delay makes the LOOKUP slow. Here the
# callee is fine and the lookup is fast and wrong: the caller talks to an address that is not
# the service. A stale DNS record or a bad hosts entry after a migration does this.
#
# OPEN CONNECTIONS. Measured 27-11-2026: with only the hosts entry nothing happened at all - Node
# 20 keeps HTTP connections open and reuses them, so the front-end never looked the name up again.
# A wrong record bites when connections are renewed (a deploy, a reset). So after the edit the
# recipe closes the caller's open connections to the real address (`ss -K` in its network
# namespace), as a redeploy of the callee would; new connections then go to the wrong address.
#
# Restart-free: the hosts file is edited on the HOST (docker inspect HostsPath), because the
# containers run with a read-only file system. Cleanup removes the line and checks it is gone.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D10): the KERNEL shows the front-end
# sending connection attempts (SYN) to an address that never answers, and no packets to the
# catalogue's real address; METRICS show catalogue-backed pages failing or slow at the front-end
# while the catalogue's own rate drops; LOGS show the front-end's connection errors.
#
# Usage:
#   ./wrong_dns.sh inject [subtle|aggressive] | cleanup | status
# PARKED 27-11-2026: with the connections closed, the front-end crash-looped (restarts 11 -> 20)
# and the site served nothing, also after cleanup - the same host-wide outage as conntrack_full.
#   env: WRONG_IP (default 10.255.255.1: a private address with no host behind it)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fault_lib.sh"

CALLER_SVC="${CALLER_SVC:-front-end}"
TARGET_SVC="${TARGET_SVC:-catalogue}"
FAULT_FAMILY="D_dependency"
FAULT_NAME="wrong_dns_${TARGET_SVC}"
FAULT_SCOPE="service"
TARGET_SERVICE="$TARGET_SVC"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"$CALLER_SVC\", \"$TARGET_SVC (no traffic)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-kernel}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="remove the wrong hosts entry / fix the DNS record for $TARGET_SVC"

CALLER="$(resolve_container "$CALLER_SVC")"
HOSTS="$(docker inspect -f '{{.HostsPath}}' "$CALLER")"
MARK="# strata wrong_dns"
present() { sudo grep -c "$MARK" "$HOSTS" 2>/dev/null || true; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    WRONG_IP="${WRONG_IP:-10.255.255.1}"
    case "$INTENSITY" in
      aggressive|subtle) ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    [[ -n "$HOSTS" ]] || { echo "[$FAULT_NAME] no hosts file for $CALLER"; exit 1; }
    REAL_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(resolve_container "$TARGET_SVC")")"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"caller\": \"$CALLER\", \"name\": \"$TARGET_SVC\", \"wrong_ip\": \"$WRONG_IP\", \"real_ip\": \"$REAL_IP\", \"hosts_file\": \"$HOSTS\"}"
    echo "$WRONG_IP $TARGET_SVC $MARK" | sudo tee -a "$HOSTS" > /dev/null
    CPID="$(docker inspect -f '{{.State.Pid}}' "$CALLER")"
    K=$(sudo nsenter -t "$CPID" -n ss -tnH state established dst "$REAL_IP" | wc -l)
    sudo nsenter -t "$CPID" -n ss -K -tn dst "$REAL_IP" > /dev/null 2>&1 || true
    echo "[$FAULT_NAME] closed $K open connections from $CALLER to $REAL_IP (left: $(sudo nsenter -t "$CPID" -n ss -tnH state established dst "$REAL_IP" | wc -l))"
    echo "[$FAULT_NAME] $CALLER now resolves $TARGET_SVC to $WRONG_IP (real $REAL_IP); entries: $(present)"
    ;;
  cleanup)
    sudo sed -i "/$MARK/d" "$HOSTS"
    N="$(present)"
    [[ "$N" == "0" ]] || echo "[$FAULT_NAME] WARN: $N wrong entries are still in $HOSTS"
    echo "[$FAULT_NAME] hosts entry removed (left: $N)"
    gt_end
    ;;
  status)
    echo "$CALLER hosts file: $(present) wrong entries; lookup now: $(docker exec "$CALLER" getent hosts "$TARGET_SVC" 2>/dev/null | head -1)"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
