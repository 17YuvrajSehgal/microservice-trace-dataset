# slow_consumer (Python, queue.Queue). See ../problem.sh.
import os
import queue
import threading
import time

q = queue.Queue()
fault = False
stat_lock = threading.Lock()
consumed = 0
age_max = 0.0


def producer():                  # one 8 KB item every 2 ms
    nxt = time.monotonic()
    while True:
        nxt += 0.002
        d = nxt - time.monotonic()
        if d > 0:
            time.sleep(d)
        q.put((time.monotonic(), bytes(8192)))


def consumer():
    global consumed, age_max
    while True:
        t, _ = q.get()
        age = time.monotonic() - t
        if fault:
            time.sleep(0.003)
        else:
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.001:
                pass
        with stat_lock:
            consumed += 1
            age_max = max(age_max, age)


flag = os.environ.get("V4_FLAG", "/dev/shm/v4_fault")
threading.Thread(target=producer, name="sc_producer", daemon=True).start()
threading.Thread(target=consumer, name="sc_consumer", daemon=True).start()
tick = 0
while True:
    time.sleep(0.1)
    tick += 1
    fault = os.path.exists(flag)
    if tick % 10:
        continue
    with stat_lock:
        n, a = consumed, age_max
        consumed, age_max = 0, 0.0
    print(f"stats consumed={n} queue_len={q.qsize()} item_age_ms={a * 1e3:.3f} fault={int(fault)}", flush=True)
