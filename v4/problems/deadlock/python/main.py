# deadlock (Python, threading.Lock). See ../problem.sh.
import os
import threading
import time

A, B = threading.Lock(), threading.Lock()
done = 0
done_lock = threading.Lock()


def spin_us(us):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < us / 1e6:
        pass


def worker():
    global done
    while True:
        with A:
            with B:
                spin_us(50)
        with done_lock:
            done += 1
        time.sleep(0.001)


def wrong_order():               # the fault: B first, then A
    while True:
        with B:
            time.sleep(0.001)
            with A:
                spin_us(50)
        time.sleep(0.001)


flag = os.environ.get("V4_FLAG", "/dev/shm/v4_fault")
for _ in range(8):
    threading.Thread(target=worker, name="dl_worker", daemon=True).start()
started = 0
while True:
    time.sleep(1)
    if not started and os.path.exists(flag):
        threading.Thread(target=wrong_order, name="dl_wrong_order", daemon=True).start()
        started = 1
    with done_lock:
        n, done = done, 0
    print(f"stats done={n} wrong_order={started}", flush=True)
