#!/usr/bin/env python3
"""Real lock contention: many threads fighting over one briefly-held lock.

WHY THE SHAPE MATTERS MORE THAN THE TOTAL
-----------------------------------------
Finding F22 measured total futex wait across all 13 fault families and found it FLAT - the
largest move was 1.38x. So we already have the negative control. What we have never had is a
positive example.

The same finding also showed how a naive lock blueprint fails. On the first probe, total futex
wait was 408 seconds per second of wall clock, and `java` alone waited 6,684 s across 22,036
calls - about 300 ms each. That is thread pools PARKED WAITING FOR WORK, not contention. Idle
parking swamps the total by orders of size.

Contention has the opposite shape:

    idle parking   few waits, each long      (a pool thread blocked on an empty queue)
    contention     many waits, each short    (the holder releases, a waiter wakes and re-blocks)

So this workload is deliberately built to produce the second shape: a short critical section
hammered by many threads, giving a high RATE of short futex waits rather than a large total.

CPython's threading.Lock is a real futex on Linux, so `syscall_entry_futex` /
`syscall_exit_futex` capture the waits directly - and we already record every syscall, which is
why F22 could be measured on traces collected before anyone thought to look.

    python3 lock_contention.py [threads] [hold_us] [work_us]
"""
import os
import sys
import threading
import time

THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 16
HOLD_US = int(sys.argv[2]) if len(sys.argv) > 2 else 200     # critical section length
WORK_US = int(sys.argv[3]) if len(sys.argv) > 3 else 50      # work done OUTSIDE the lock

lock = threading.Lock()
stop = threading.Event()
acquires = [0] * THREADS


def spin(us):
    """Busy-wait. sleep() would put the thread on a timer instead of contending."""
    end = time.perf_counter() + us / 1e6
    while time.perf_counter() < end:
        pass


def worker(idx):
    n = 0
    while not stop.is_set():
        spin(WORK_US)          # outside the lock, so threads arrive staggered
        with lock:             # <- the contended section
            spin(HOLD_US)
            n += 1
        acquires[idx] = n


def main():
    print(f"lock_contention: {THREADS} threads, hold {HOLD_US}us, work {WORK_US}us, "
          f"pid {os.getpid()}", flush=True)
    threads = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(THREADS)]
    for t in threads:
        t.start()
    try:
        last = 0
        while True:
            time.sleep(10)
            total = sum(acquires)
            print(f"  acquisitions: {total} (+{total - last} in 10s)", flush=True)
            last = total
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
