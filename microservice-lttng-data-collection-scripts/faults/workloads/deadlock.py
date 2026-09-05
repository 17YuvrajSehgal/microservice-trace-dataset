#!/usr/bin/env python3
"""Deadlock: two locks, two threads, opposite order. The waits never end.

WHY THIS IS A SEPARATE FAMILY FROM lock_contention
--------------------------------------------------
Both are threads blocked on a lock, so both show futex waits. The difference is the ending:

    lock_contention   many waits, each SHORT     - the holder always releases
    deadlock          few waits, each INFINITE   - the holder never releases

That makes deadlock the closer look-alike of `dependency_outage`, not of contention: both go
silent and stop serving. The distinction worth measuring is that a deadlocked process still
HOLDS its threads - they sit in futex forever - while a paused container's threads are simply
never scheduled. Findings F11-F13 established that a paused container cannot be seen in the
scheduler stream at all; a deadlock should be visible, because the threads are genuinely
blocked in a syscall rather than frozen outside one.

If that turns out to be true, it is a discriminator we do not currently have. If it turns out
false, that is a real negative result about the limits of kernel-only diagnosis.

DESIGN
------
A fresh pair of threads deadlocks every `respawn` seconds, so the number of stuck threads grows
steadily through the injection window rather than being a single event at the start. That gives
the trace a gradient to measure instead of one instant.

Threads are daemons and the whole thing lives in a container, so cleanup is `docker rm -f` -
there is no way to unwedge a real deadlock, which is rather the point.

    python3 deadlock.py [respawn_s] [max_pairs]
"""
import os
import sys
import threading
import time

RESPAWN_S = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
MAX_PAIRS = int(sys.argv[2]) if len(sys.argv) > 2 else 12

stuck = {"pairs": 0}


def deadlock_pair(idx):
    """Two threads, two locks, acquired in opposite orders. Textbook AB-BA."""
    a, b = threading.Lock(), threading.Lock()

    def ab():
        with a:
            time.sleep(0.05)      # let the other thread take b before we ask for it
            with b:               # blocks forever
                pass

    def ba():
        with b:
            time.sleep(0.05)
            with a:               # blocks forever
                pass

    threading.Thread(target=ab, daemon=True, name=f"ab{idx}").start()
    threading.Thread(target=ba, daemon=True, name=f"ba{idx}").start()


def main():
    print(f"deadlock: a new stuck pair every {RESPAWN_S}s, up to {MAX_PAIRS} pairs, "
          f"pid {os.getpid()}", flush=True)
    try:
        while stuck["pairs"] < MAX_PAIRS:
            deadlock_pair(stuck["pairs"])
            stuck["pairs"] += 1
            print(f"  stuck pairs: {stuck['pairs']} "
                  f"({2 * stuck['pairs']} threads blocked forever), "
                  f"live threads {threading.active_count()}", flush=True)
            time.sleep(RESPAWN_S)
        # hold the process open so the blocked threads stay in the trace
        while True:
            time.sleep(10)
            print(f"  holding {2 * stuck['pairs']} deadlocked threads", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
