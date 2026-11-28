# priority_inversion (Python). Each role thread writes its kernel thread id so the runner can give
# it a real-time priority. threading.Lock has no priority inheritance, and the GIL is a second lock
# every thread needs. See ../problem.sh.
import os
import threading
import time

L = threading.Lock()
stat_lock = threading.Lock()
fault = False
cycles = wait = wait_max = 0.0


def spin_us(us):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < us / 1e6:
        pass


def report_tid(role):
    with open(os.environ.get("V4_TIDS", "/dev/shm/v4_tids"), "a") as f:
        f.write(f"{role} {threading.get_native_id()}\n")


def low():
    report_tid("low")
    while True:
        with L:
            spin_us(5000)
        time.sleep(0.015)


def mid(name):
    report_tid(name)
    while True:
        if fault:
            spin_us(50000)
            time.sleep(0.002)
        else:
            time.sleep(0.1)


def high():
    global cycles, wait, wait_max
    report_tid("high")
    while True:
        t0 = time.perf_counter()
        with L:
            w = time.perf_counter() - t0
            spin_us(200)
        with stat_lock:
            cycles += 1
            wait += w
            wait_max = max(wait_max, w)
        time.sleep(0.01)


flag = os.environ.get("V4_FLAG", "/dev/shm/v4_fault")
threading.Thread(target=low, name="low", daemon=True).start()
threading.Thread(target=mid, args=("mid1",), name="mid1", daemon=True).start()
threading.Thread(target=mid, args=("mid2",), name="mid2", daemon=True).start()
threading.Thread(target=high, name="high", daemon=True).start()
tick = 0
while True:
    time.sleep(0.1)
    tick += 1
    fault = os.path.exists(flag)
    if tick % 10:
        continue
    with stat_lock:
        n, w, mx = cycles, wait, wait_max
        cycles = wait = wait_max = 0
    print(f"stats high_cycles={int(n)} high_wait_avg_ms={(w / n * 1e3) if n else 0:.3f} high_wait_max_ms={mx * 1e3:.3f} fault={int(fault)}", flush=True)
