// lock_contention (Java, ReentrantLock). See ../problem.sh.
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

public class Main {
    static final ReentrantLock M = new ReentrantLock();
    static volatile boolean fault = false;
    static final AtomicLong done = new AtomicLong(), waitNs = new AtomicLong(), waitMax = new AtomicLong();

    static void spinUs(long us) {
        long t0 = System.nanoTime();
        while (System.nanoTime() - t0 < us * 1000) { }
    }

    public static void main(String[] args) throws Exception {
        String flag = System.getenv().getOrDefault("V4_FLAG", "/dev/shm/v4_fault");
        for (int i = 0; i < 16; i++) {
            Thread t = new Thread(() -> {
                for (;;) {
                    long t0 = System.nanoTime();
                    M.lock();
                    long w = System.nanoTime() - t0;
                    spinUs(fault ? 2000 : 20);
                    M.unlock();
                    done.incrementAndGet();
                    waitNs.addAndGet(w);
                    waitMax.accumulateAndGet(w, Math::max);
                    try { Thread.sleep(1); } catch (InterruptedException e) { }
                }
            }, "lc_worker");
            t.setDaemon(true);
            t.start();
        }
        for (int tick = 1;; tick++) {
            Thread.sleep(100);
            fault = Files.exists(Paths.get(flag));
            if (tick % 10 != 0) continue;
            long n = done.getAndSet(0), w = waitNs.getAndSet(0), mx = waitMax.getAndSet(0);
            System.out.printf("stats done=%d wait_avg_ms=%.3f wait_max_ms=%.3f fault=%d%n",
                    n, n > 0 ? w / 1e6 / n : 0.0, mx / 1e6, fault ? 1 : 0);
        }
    }
}
