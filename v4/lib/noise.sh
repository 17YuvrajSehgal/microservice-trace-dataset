#!/bin/bash
# noise.sh - the same background activity in every v4 run, fault or healthy, so that the faulty
# program is never the only thing happening on the host:
#   - a small web server on localhost with a client asking it about 20 times a second
#     (short-lived curl processes: process starts and exits, sockets, a little CPU)
#   - a compression job: 20 MB through gzip every 5 s (bursts of CPU and file reads)
#   - a periodic job: sha256sum of a 5 MB file every 2 s
#
#   noise.sh start <logs_dir> | stop
set -uo pipefail
D=/var/tmp/v4noise
PIDS=/dev/shm/v4_noise.pids
case "${1:-}" in
  start)
    L="${2:?logs dir}"
    mkdir -p "$D/www"
    [[ -s "$D/big.bin" ]] || head -c 20M /dev/urandom > "$D/big.bin"
    [[ -s "$D/mid.bin" ]] || head -c 5M /dev/urandom > "$D/mid.bin"
    [[ -s "$D/www/index.html" ]] || head -c 4096 /dev/urandom | base64 > "$D/www/index.html"
    : > "$PIDS"
    (cd "$D/www" && exec setsid python3 -m http.server 8090 --bind 127.0.0.1 > "$L/noise_web.log" 2>&1) & echo $! >> "$PIDS"
    setsid bash -c 'while :; do curl -s -o /dev/null http://127.0.0.1:8090/index.html; sleep 0.05; done' > /dev/null 2>&1 & echo $! >> "$PIDS"
    setsid bash -c "while :; do gzip -c $D/big.bin > /dev/null; sleep 5; done" > /dev/null 2>&1 & echo $! >> "$PIDS"
    setsid bash -c "while :; do sha256sum $D/mid.bin > /dev/null; sleep 2; done" > /dev/null 2>&1 & echo $! >> "$PIDS"
    sleep 1
    ;;
  stop)
    [[ -f "$PIDS" ]] && while read -r p; do kill -TERM -- "-$p" 2>/dev/null; kill -TERM "$p" 2>/dev/null; done < "$PIDS"
    pkill -f "http.server 8090" 2>/dev/null
    rm -f "$PIDS"
    ;;
  *) echo "usage: $0 start <logs_dir> | stop"; exit 1 ;;
esac
