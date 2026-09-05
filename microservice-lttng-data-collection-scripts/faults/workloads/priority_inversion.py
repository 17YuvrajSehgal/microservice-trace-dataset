#!/usr/bin/env python3
"""Priority inversion: the case where everything stalls and nothing looks busy.

THE CLASSIC BUG
---------------
    LOW  priority thread takes a lock
    HIGH priority thread wants the same lock, so it blocks
    MID  priority threads hog the CPU, so LOW never gets scheduled to release it

Result: the highest-priority work is blocked, indirectly, by work of MIDDLE priority that it
never interacts with. This is the Mars Pathfinder bug, and it is exactly the shape Naser asked
for - the agent alone should fail, because no resource looks saturated in an interesting way:

    CPU        busy, but with MID work that is behaving normally
    disk       idle
    network    idle
    the lock   held by a thread that is not running

Nothing points at LOW, which is the actual culprit.

WHY nice AND NOT REAL-TIME PRIORITIES
-------------------------------------
The textbook demonstration uses SCHED_FIFO. We deliberately do not: a spinning real-time
thread can make a machine unresponsive, and this runs unattended for 120 s next to a live
application. `nice` inversion is weaker but produces the same structure, and the container is
CPU-capped as a second guard.

WHAT THE KERNEL SHOWS
---------------------
    sched_switch      LOW is runnable but rarely on-CPU, while MID runs constantly
    futex             HIGH's wait is LONG and there are FEW of them
                      (the opposite of lock_contention: few waits, each long)

That contrast is the discriminator between these two concurrency faults, and it is why they
are collected as separate families rather than one.

    python3 priority_inversion.py [mid_threads] [hold_ms]
"""
import os
import sys
import threading
import time

MID_THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
HOLD_MS = int(sys.argv[2]) if len(sys.argv) > 2 else 50

lock = threading.Lock()
stop = threading.Event()
stats = {"high_waits": 0, "high_wait_total": 0.0, "low_acquires": 0, "mid_loops": 0}


def spin(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def renice(delta):
    """Lower this thread's priority. Linux nice is per-thread despite the POSIX wording."""
    try:
        os.nice(delta)
    except OSError:
        pass


def low_priority_holder():
    renice(19)                       # the most generous: yields to everything
    while not stop.is_set():
        with lock:
            spin(HOLD_MS / 1000.0)   # holds the lock while barely getting scheduled
            stats["low_acquires"] += 1
        time.sleep(0.001)


def mid_priority_hog():
    renice(0)                        # ordinary priority - just busy
    while not stop.is_set():
        spin(0.05)
        stats["mid_loops"] += 1


def high_priority_waiter():
    renice(-5)                       # best effort; needs privilege, harmless if refused
    while not stop.is_set():
        t0 = time.perf_counter()
        with lock:
            pass                     # the work is trivial - the WAIT is the fault
        waited = time.perf_counter() - t0
        stats["high_waits"] += 1
        stats["high_wait_total"] += waited
        time.sleep(0.01)


def main():
    print(f"priority_inversion: 1 low holder, {MID_THREADS} mid hogs, 1 high waiter, "
          f"hold {HOLD_MS}ms, pid {os.getpid()}", flush=True)
    ts = [threading.Thread(target=low_priority_holder, daemon=True),
          threading.Thread(target=high_priority_waiter, daemon=True)]
    ts += [threading.Thread(target=mid_priority_hog, daemon=True)
           for _ in range(MID_THREADS)]
    for t in ts:
        t.start()
    try:
        while True:
            time.sleep(10)
            n = stats["high_waits"] or 1
            print(f"  high-priority waits: {stats['high_waits']}, "
                  f"mean wait {1000 * stats['high_wait_total'] / n:.1f} ms, "
                  f"low acquired {stats['low_acquires']}", flush=True)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
