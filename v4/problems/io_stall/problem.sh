# io_stall - the file system under a writer freezes for seconds at a time.
# The program appends a 4 KB record and calls fsync every 5 ms, on a small ext4 file system of its
# own (/mnt/v4io, a loop device made by setup_vm.sh, so the rest of the host is not touched). With
# the fault on, the file system is frozen (fsfreeze) for 2 s out of every 6 s: the writer's write
# and fsync block in the kernel until it is thawed.
CAND="H4 (I/O stall, v4 controlled tier)"
MECH="a writer appends 4 KB + fsync every 5 ms on /mnt/v4io; with the fault the file system is frozen 2 s in every 6 s"
REMEDIATION="find what freezes or stalls the device (a snapshot, a backup tool, a failing disk) and stop it"
LANGS="c go java python node"
SHORT=iostall
KPI=op_max_ms; KPI_DIR=up; KPI_FACTOR=10
MNT=/mnt/v4io
FREEZER=/dev/shm/v4_freezer.pid
setup_run() {
    mountpoint -q "$MNT" || { echo "[v4] $MNT is not mounted: run v4/lib/setup_vm.sh"; exit 1; }
    sudo fsfreeze -u "$MNT" 2>/dev/null
    rm -f "$MNT"/*.dat
}
inject_fault() {
    setsid bash -c "while :; do sudo fsfreeze -f $MNT; sleep 2; sudo fsfreeze -u $MNT; sleep 4; done" > /dev/null 2>&1 &
    echo $! > "$FREEZER"
    echo "[v4] freezing $MNT 2 s in every 6 s"
}
cleanup_fault() {
    [[ -f "$FREEZER" ]] && kill -TERM -- "-$(cat "$FREEZER")" 2>/dev/null
    rm -f "$FREEZER"
    sleep 0.5
    sudo fsfreeze -u "$MNT" 2>/dev/null
    return 0
}
