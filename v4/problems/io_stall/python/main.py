# io_stall (Python): append 4 KB and fsync every 5 ms, reporting how long each write+fsync took.
# See ../problem.sh.
import os
import time

fd = os.open("/mnt/v4io/python.dat", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
buf = b"x" * 4096
ops, total, mx = 0, 0.0, 0.0
nxt = time.monotonic()
report = nxt + 1
while True:
    t0 = time.monotonic()
    os.write(fd, buf)
    os.fsync(fd)
    d = time.monotonic() - t0
    ops += 1
    total += d
    mx = max(mx, d)
    if time.monotonic() >= report:
        print(f"stats ops={ops} op_avg_ms={(total / ops * 1e3) if ops else 0:.3f} op_max_ms={mx * 1e3:.3f}", flush=True)
        ops, total, mx = 0, 0.0, 0.0
        report += 1
        if time.monotonic() > report:
            report = time.monotonic() + 1
    nxt += 0.005
    if time.monotonic() > nxt:
        nxt = time.monotonic()
    time.sleep(max(0, nxt - time.monotonic()))
