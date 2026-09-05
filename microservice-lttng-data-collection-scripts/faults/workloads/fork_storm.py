""" Rapid, BOUNDED process creation.

WHAT THIS IS AND IS NOT
-----------------------
Not a fork bomb. A fork bomb is unbounded and recursive and would take the machine down; this
runs beside a live application for 120 s. Here the number of live children is capped, each one
exits on its own, and the container has a hard PID limit as a second guard. If the cap is ever
reached the loop waits instead of spawning.

WHY IT IS WORTH A FAMILY
------------------------
`sched_process_fork` is unmistakable, and nothing else in our dataset produces it in volume.
That makes it the cheapest possible positive control for the whole scheduler pipeline: if a
blueprint cannot see this, something is wrong with the analysis rather than with the fault.

It is also a real production shape. A crash-looping container, a runaway supervisor, or a
shell script spawning per-item processes all look like this, and all of them are usually
diagnosed late because nothing else is saturated.

    python3 fork_storm.py [spawns_per_second] [max_live] [child_lifetime_s]
"""
import os
import signal
import sys
import time

RATE = int(sys.argv[1]) if len(sys.argv) > 1 else 50
MAX_LIVE = int(sys.argv[2]) if len(sys.argv) > 2 else 200
LIFETIME = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

live = set()


def reap():
    """Collect finished children so they do not accumulate as zombies."""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return
        live.discard(pid)


def spawn_one():
    pid = os.fork()
    if pid == 0:
        # child: sleep briefly, then exit. No work, no recursion - the fork itself is the
        # signal we are producing.
        try:
            time.sleep(LIFETIME)
        finally:
            os._exit(0)
    live.add(pid)


def main():
    print(f"fork_storm: {RATE}/s, at most {MAX_LIVE} live, children live {LIFETIME}s, "
          f"pid {os.getpid()}", flush=True)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    total = 0
    try:
        while True:
            t0 = time.perf_counter()
            for _ in range(RATE):
                reap()
                if len(live) >= MAX_LIVE:
                    break                      # the cap: wait rather than spawn
                try:
                    spawn_one()
                    total += 1
                except OSError as e:
                    print(f"  fork refused ({e}) - cap reached", flush=True)
                    break
            delay = 1.0 - (time.perf_counter() - t0)
            if delay > 0:
                time.sleep(delay)
            if total % (RATE * 10) < RATE:
                print(f"  forked {total} total, {len(live)} live", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        for pid in list(live):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


if __name__ == "__main__":
    main()
