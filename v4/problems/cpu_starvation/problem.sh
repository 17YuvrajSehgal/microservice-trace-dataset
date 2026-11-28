# cpu_starvation - a periodic task shares its CPU with busy neighbours.
# The program runs one periodic task on CPU 10: every 10 ms it wakes up and does 1 ms of work, and
# reports how late each wake-up was. With the fault on, three CPU-bound processes (stress-ng) are
# started on the same CPU at the same priority; the task waits in the run queue before it runs.
# The fault is outside the program, so the five languages differ only in the task itself.
CAND="(blueprint 8 cpu_starvation, v4 controlled tier)"
MECH="a 10 ms periodic task pinned to CPU 10; with the fault 3 busy processes run on the same CPU"
REMEDIATION="move the busy processes off that CPU (or give the periodic task its own CPU / a higher priority)"
LANGS="c go java python node"
SHORT=cpustarve
PIN_CPU=10
KPI=late_p99_ms; KPI_DIR=up; KPI_FACTOR=4
HOGS=/dev/shm/v4_hogs.pid
inject_fault() {
    setsid stress-ng --cpu 3 --taskset "$PIN_CPU" --cpu-method int64 --quiet > /dev/null 2>&1 &
    echo $! > "$HOGS"
    sleep 1
    echo "[v4] hogs on CPU $PIN_CPU: $(pgrep -c stress-ng)"
}
cleanup_fault() {
    [[ -f "$HOGS" ]] && kill -TERM -- "-$(cat "$HOGS")" 2>/dev/null
    pkill -f "stress-ng --cpu 3 --taskset" 2>/dev/null
    rm -f "$HOGS"
}
