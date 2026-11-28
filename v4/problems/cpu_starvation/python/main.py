# cpu_starvation (Python): a 10 ms periodic task with 1 ms of work, reporting its wake-up lateness.
# See ../problem.sh.
import time

late = []
nxt = time.monotonic()
report = nxt + 1
while True:
    nxt += 0.010
    d = nxt - time.monotonic()
    if d > 0:
        time.sleep(d)
    t = time.monotonic()
    late.append(t - nxt)
    while time.monotonic() - t < 0.001:      # 1 ms of work
        pass
    if t >= report:
        s = sorted(late)
        n = len(s)
        print(f"stats ticks={n} late_p50_ms={s[n // 2] * 1e3:.3f} late_p99_ms={s[n * 99 // 100] * 1e3:.3f} late_max_ms={s[-1] * 1e3:.3f}", flush=True)
        late = []
        report += 1
    if time.monotonic() > nxt + 0.010:
        nxt = time.monotonic()
