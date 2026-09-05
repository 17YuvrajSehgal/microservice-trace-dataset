#!/usr/bin/env python3
"""Concurrent load probe that measures the SERVICE and not the shell.

WHY THIS EXISTS
---------------
Three attempts to smoke-test the serialising code defects were defeated by the measurement
rather than the defect:

  1. sequential curl        a lock held across I/O costs nothing with one request in flight
  2. curl through the proxy the front end added ~35 ms, swamping a serialised 2 ms query
  3. xargs -P with curl     300 process spawns dominated the total; on/off differed by 1 ms

All three reported a working defect as doing nothing. A defect wrongly declared dead gets
tuned or dropped, so the measurement has to be trustworthy before its verdict means anything.

One process, real threads, keep-alive connections, and only summary numbers on stdout.

    python3 loadprobe.py <url> [requests] [concurrency]
"""
from __future__ import annotations
import statistics
import sys
import threading
import time
import urllib.request

URL = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 400
CONC = int(sys.argv[3]) if len(sys.argv) > 3 else 60

lat: list[float] = []
errors = [0]
lock = threading.Lock()
work = list(range(N))
idx = [0]


def worker():
    opener = urllib.request.build_opener()
    while True:
        with lock:
            if idx[0] >= N:
                return
            idx[0] += 1
        t0 = time.perf_counter()
        try:
            with opener.open(URL, timeout=20) as r:
                r.read()
            dt = (time.perf_counter() - t0) * 1000.0
            with lock:
                lat.append(dt)
        except Exception:                                              # noqa: BLE001
            with lock:
                errors[0] += 1


def main():
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(CONC)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.perf_counter() - t0) * 1000.0
    if not lat:
        print("p50=0 p95=0 wall=0 errors=%d" % errors[0])
        return 1
    s = sorted(lat)
    print("p50=%.1f p95=%.1f wall=%.0f n=%d errors=%d"
          % (statistics.median(s), s[int(0.95 * len(s)) - 1], wall, len(s), errors[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
