#!/usr/bin/env python3
# stamp.py - put a UTC time in front of every line on stdin (the format of Docker's log files, so
# the log tools read v4 logs the same way: "2026-11-28T10:00:00.123456789Z <line>").
import sys
import time

for line in sys.stdin:
    t = time.time()
    sys.stdout.write(time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%09dZ " % int((t % 1) * 1e9) + line)
    sys.stdout.flush()
