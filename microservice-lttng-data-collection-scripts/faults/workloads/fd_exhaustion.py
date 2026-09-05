#!/usr/bin/env python3
"""Exhaust file descriptors, then hold them.

WHY THIS SIGNATURE IS UNUSUALLY CLEAN
-------------------------------------
We record every syscall WITH ITS RETURN VALUE. When descriptors run out, `open`, `socket` and
`accept` start returning EMFILE (-24). That is not an inference from timing or a ratio against
a baseline - it is the kernel stating the error directly, on every failed call.

Almost nothing else in our dataset is that explicit. Most of our faults have to be diagnosed
from a change in a distribution; this one announces itself.

WHY IT PAIRS WITH dependency_outage
-----------------------------------
Both end with a service that stops serving. The difference:

    fd_exhaustion       the service is running and FAILING at a specific syscall
    dependency_outage   the service is not running at all

Findings F11-F13 showed a paused container is invisible in the scheduler stream. This one
should be loud. If a blueprint can separate "failing" from "absent", that is a discriminator
worth having.

DESIGN
------
Descriptors are taken in a controlled ramp rather than all at once, so the trace shows the
approach to the limit and not just the wall. Everything is held open until the process exits,
so `docker rm -f` or a process kill is a complete cleanup - nothing survives the container.

    python3 fd_exhaustion.py [target_fds] [ramp_seconds]
"""
import errno
import os
import resource
import socket
import sys
import time

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
RAMP_S = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

held = []


def raise_soft_limit():
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
        soft = hard
    except (ValueError, OSError):
        pass
    return soft, hard


def main():
    soft, hard = raise_soft_limit()
    print(f"fd_exhaustion: target {TARGET}, rlimit soft={soft} hard={hard}, "
          f"pid {os.getpid()}", flush=True)

    # Ramp rather than a spike: the interesting part of the trace is the APPROACH to the
    # limit, where some calls still succeed, not only the flat wall afterwards.
    batch = max(1, TARGET // max(1, int(RAMP_S * 10)))
    emfile = 0
    t_end = time.time() + RAMP_S
    while len(held) < TARGET:
        for _ in range(batch):
            try:
                # a socket, not a file: it takes a descriptor without touching the disk, so
                # this stays a descriptor fault and does not become a disk fault
                held.append(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            except OSError as e:
                if e.errno in (errno.EMFILE, errno.ENFILE):
                    emfile += 1
                    if emfile == 1:
                        print(f"  LIMIT REACHED at {len(held)} descriptors "
                              f"({errno.errorcode[e.errno]})", flush=True)
                    break
                raise
        if emfile:
            break
        if time.time() < t_end:
            time.sleep(0.1)
    print(f"  holding {len(held)} descriptors, {emfile} refusals so far", flush=True)

    # Keep failing, so the EMFILE returns keep appearing through the whole window rather than
    # only at the moment the limit was hit.
    try:
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                held.append(s)
            except OSError as e:
                if e.errno in (errno.EMFILE, errno.ENFILE):
                    emfile += 1
            time.sleep(0.01)
            if emfile % 500 == 0 and emfile:
                print(f"  refusals: {emfile}, held {len(held)}", flush=True)
                emfile += 1
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
