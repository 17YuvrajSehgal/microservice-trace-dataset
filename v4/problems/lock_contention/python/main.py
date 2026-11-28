# lock_contention (Python, threading.Lock). See ../problem.sh.
# In CPython the global interpreter lock (GIL) is also taken by every thread that runs Python code,
# so a busy critical section here competes for two locks. That is part of what v4 measures.
import os
import threading
import time

M = threading.Lock()
stat_lock = threading.Lock()
fault = False
done = wait = wait_max = 0.0


def spin_us(us):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < us / 1e6:
        pass


def worker():
    global done, wait, wait_max
    while True:
        t0 = time.perf_counter()
        with M:
            w = time.perf_counter() - t0
            spin_us(2000 if fault else 20)
        with stat_lock:
            done += 1
            wait += w
            wait_max = max(wait_max, w)
        time.sleep(0.001)


flag = os.environ.get("V4_FLAG", "/dev/shm/v4_fault")
for _ in range(16):
    threading.Thread(target=worker, name="lc_worker", daemon=True).start()
tick = 0
while True:
    time.sleep(0.1)
    tick += 1
    fault = os.path.exists(flag)
    if tick % 10:
        continue
    with stat_lock:
        n, w, mx = done, wait, wait_max
        done = wait = wait_max = 0
    print(f"stats done={int(n)} wait_avg_ms={(w / n * 1e3) if n else 0:.3f} wait_max_ms={mx * 1e3:.3f} fault={int(fault)}", flush=True)
