#!/bin/bash
# setup_vm.sh - prepare the collection VM for v4 runs. Safe to run again (every chain starts with it).
#   1. the toolchains for the five languages, stress-ng (CPU hogs), pigz
#   2. a small ext4 file system on a loop device at /mnt/v4io (io_stall freezes THIS, never the root)
#   3. stop every Docker container (Sock Shop), so v4 runs see only their program and the noise.
#      The list is kept in ~/v4_stopped_containers.txt; `docker start $(cat ...)` brings them back.
#      They come back by themselves after a reboot (restart: always), so every chain runs this first.
set -uo pipefail
need=""
for p in gcc golang-go openjdk-21-jdk-headless nodejs stress-ng pigz; do dpkg -s "$p" > /dev/null 2>&1 || need="$need $p"; done
if [[ -n "$need" ]]; then
    echo "[setup] installing:$need"
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq > /dev/null
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $need > /dev/null || { echo "[setup] apt failed"; exit 1; }
fi
echo "[setup] gcc $(gcc -dumpversion), $(go version | cut -d' ' -f3), java $(java -version 2>&1 | head -1 | cut -d'"' -f2), node $(node --version), python $(python3 --version | cut -d' ' -f2)"

IMG=/var/lib/v4io.img MNT=/mnt/v4io
if ! mountpoint -q "$MNT"; then
    [[ -f "$IMG" ]] || { sudo truncate -s 2G "$IMG" && sudo mkfs.ext4 -q -F "$IMG"; }
    sudo mkdir -p "$MNT" && sudo mount -o loop "$IMG" "$MNT" && sudo chown "$USER" "$MNT"
fi
mountpoint -q "$MNT" && echo "[setup] $MNT mounted on $(findmnt -no SOURCE "$MNT")" || { echo "[setup] $MNT NOT mounted"; exit 1; }

running=$(docker ps -q 2>/dev/null)
if [[ -n "$running" ]]; then
    docker ps --format '{{.Names}}' >> ~/v4_stopped_containers.txt
    sort -u -o ~/v4_stopped_containers.txt ~/v4_stopped_containers.txt
    docker stop $running > /dev/null && echo "[setup] stopped $(echo "$running" | wc -l) containers"
fi
echo "[setup] containers running now: $(docker ps -q | wc -l)"
