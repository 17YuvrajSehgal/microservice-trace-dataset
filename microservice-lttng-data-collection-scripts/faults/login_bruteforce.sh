#!/bin/bash
# Fault recipe: login brute force against the shop (security family).
#
# A client tries logins for one existing user with wrong passwords, RATE times per second. Each
# attempt fails quickly with 401. Nothing is slow and nothing breaks for other users.
#
# A BENIGN SIMULATION on our own isolated VM against our own shop; the password guesses are
# random strings and the account is the demo account of the stack.
#
# WHY THIS FAMILY. The other security families are seen in CPU (resource_abuse), bytes
# (data_exfiltration) or connection fan-out (port_scan). This one is seen in the APPLICATION's
# answers: a steady stream of failed logins from one client, which the user service logs.
#
# The client runs on the host, like the load generator, so its requests enter through the edge
# router like any user's. Restart-free; cleanup stops it.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS G2): LOGS (user service, front-end) and
# METRICS (401 rate at the front-end) show it at once; spans show many short login calls ending
# in 401; the KERNEL shows only more short requests from the host. Measured in calibration.
#
# Usage:
#   ./login_bruteforce.sh inject [subtle|aggressive] | cleanup | status
#   env: RATE (attempts per second), LOGIN_USER
set -euo pipefail
_SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SD/fault_lib.sh"

FAULT_FAMILY="G_security"
FAULT_NAME="login_bruteforce"
FAULT_SCOPE="service"
TARGET_SERVICE="user"
EXPECTED_BLAST_RADIUS="${EXPECTED_BLAST_RADIUS:-[\"none (no user-visible effect expected)\"]}"
EXPECTED_WINNING_MODALITY="${EXPECTED_WINNING_MODALITY:-logs}"
TARGET_TRACE_VISIBILITY="${TARGET_TRACE_VISIBILITY:-covered}"
REMEDIATION="block the client and lock or rate-limit logins for the targeted account"

PIDFILE="$FAULT_STATE_DIR/${FAULT_NAME}.pid"
LOG="$FAULT_STATE_DIR/${FAULT_NAME}.client.log"
running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  inject)
    INTENSITY="${2:-aggressive}"
    case "$INTENSITY" in
      aggressive) RATE="${RATE:-50}" ;;
      subtle)     RATE="${RATE:-5}" ;;
      *) echo "unknown intensity: $INTENSITY"; exit 1 ;;
    esac
    LOGIN_USER="${LOGIN_USER:-Eve_Berger}"
    mkdir -p "$FAULT_STATE_DIR"
    # gt_begin FIRST: it stamps the start of the incident window.
    gt_begin "$INTENSITY" "{\"attempts_per_second\": $RATE, \"account\": \"$LOGIN_USER\", \"source\": \"host\"}"
    nohup python3 -u -c "
import base64, random, string, time, urllib.request, urllib.error, signal, sys
rate, user = $RATE, '$LOGIN_USER'
stop = []
signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
n = c = 0
last = time.time()
while not stop:
    t0 = time.time()
    pw = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
    req = urllib.request.Request('http://localhost:80/login', headers={'Authorization': 'Basic ' + base64.b64encode((user + ':' + pw).encode()).decode()})
    try:
        urllib.request.urlopen(req, timeout=5)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    n += 1; c += code == 401
    if time.time() - last >= 10:
        print(time.strftime('%H:%M:%S'), 'attempts', n, '401', c, flush=True); last = time.time()
    time.sleep(max(0, 1.0 / rate - (time.time() - t0)))
print('stopped: attempts', n, '401', c, flush=True)
" > "$LOG" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    sleep 2
    running || { echo "[$FAULT_NAME] the client did not start: $(tail -2 "$LOG")"; exit 1; }
    echo "[$FAULT_NAME] $RATE wrong-password logins per second for $LOGIN_USER"
    ;;
  cleanup)
    if running; then kill "$(cat "$PIDFILE")"; sleep 2; fi
    running && kill -9 "$(cat "$PIDFILE")" 2>/dev/null || true
    echo "[$FAULT_NAME] client stopped: $(tail -1 "$LOG" 2>/dev/null)"
    rm -f "$PIDFILE"
    gt_end
    ;;
  status)
    echo "brute-force client running: $(running && echo yes || echo no); last line: $(tail -1 "$LOG" 2>/dev/null)"
    ;;
  *)
    echo "usage: $0 inject [subtle|aggressive] | cleanup | status"; exit 1 ;;
esac
