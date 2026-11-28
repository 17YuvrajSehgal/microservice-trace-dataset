# priority_inversion - a high-priority thread waits for a lock held by a low-priority thread that
# medium-priority threads keep off the CPU.
# Four threads on one CPU share lock L: "low" (normal policy) holds L for 5 ms every 20 ms; "high"
# (SCHED_FIFO 50) takes L every 10 ms; two "mid" threads (SCHED_FIFO 30) are idle. With the fault
# on, the mids spin: they preempt low while low holds L, so high waits for L until the kernel's
# real-time throttling gives low a little CPU. The lock has no priority inheritance.
# The runner sets the priorities after start, by the thread ids the program writes to $V4_TIDS.
# Node.js is left out: its worker threads cannot be told apart by the runner reliably.
CAND="(blueprint 11 priority_inversion, v4 controlled tier)"
MECH="low (normal) holds L 5 ms in 20; high (FIFO 50) needs L every 10 ms; with the fault two mid threads (FIFO 30) spin on the same CPU"
REMEDIATION="use a lock with priority inheritance (PTHREAD_PRIO_INHERIT), or do not mix real-time and normal threads on one lock"
LANGS="c go java python"
SHORT=prioinv
# Only the four role threads are put on one CPU (in post_start). The first version pinned the
# whole program there; then the spinning mids also starved its own reporting thread (smoke run
# 28-11-2026: stats lines 6 s apart), and the runtime's own threads (JIT, GC) shared that CPU.
ROLE_CPU=11
KPI=high_wait_max_ms; KPI_DIR=up; KPI_FACTOR=4
post_start() {
    wait_tids 4 || return 1
    local role tid
    while read -r role tid; do
        sudo taskset -pc "$ROLE_CPU" "$tid" > /dev/null
        case "$role" in
            high) sudo chrt -f -p 50 "$tid" ;;
            mid*) sudo chrt -f -p 30 "$tid" ;;
        esac
    done < "$V4_TIDS"
    echo "[v4] roles on CPU $ROLE_CPU, priorities set: $(while read -r r t; do echo -n "$r=$(chrt -p "$t" | sed -n 's/.*policy: //p')/$(chrt -p "$t" | sed -n 's/.*priority: //p') "; done < "$V4_TIDS")"
}
