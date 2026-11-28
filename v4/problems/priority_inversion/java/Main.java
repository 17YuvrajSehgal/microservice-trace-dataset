// priority_inversion (Java). Each role thread writes its kernel thread id (read from
// /proc/thread-self) so the runner can give it a real-time priority. ReentrantLock has no priority
// inheritance. See ../problem.sh.
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

public class Main {
    static final ReentrantLock L = new ReentrantLock();
    static volatile boolean fault = false;
    static final AtomicLong cycles = new AtomicLong(), waitNs = new AtomicLong(), waitMax = new AtomicLong();

    static void spinUs(long us) { long t0 = System.nanoTime(); while (System.nanoTime() - t0 < us * 1000) { } }
    static void sleepMs(long ms) { try { Thread.sleep(ms); } catch (InterruptedException e) { } }

    static void reportTid(String role) {
        try {
            String self = Files.readSymbolicLink(Paths.get("/proc/thread-self")).toString();   // "<pid>/task/<tid>"
            String tid = self.substring(self.lastIndexOf('/') + 1);
            Files.write(Paths.get(System.getenv().getOrDefault("V4_TIDS", "/dev/shm/v4_tids")),
                    (role + " " + tid + "\n").getBytes(), StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Exception e) { System.out.println("tid error " + e); }
    }

    static void start(String name, Runnable r) {
        Thread t = new Thread(() -> { reportTid(name); r.run(); }, name);
        t.setDaemon(true);
        t.start();
    }

    public static void main(String[] args) throws Exception {
        String flag = System.getenv().getOrDefault("V4_FLAG", "/dev/shm/v4_fault");
        start("low", () -> { for (;;) { L.lock(); spinUs(5000); L.unlock(); sleepMs(15); } });
        for (String n : new String[] {"mid1", "mid2"})
            start(n, () -> { for (;;) { if (fault) { spinUs(50000); sleepMs(2); } else sleepMs(100); } });
        start("high", () -> {
            for (;;) {
                long t0 = System.nanoTime();
                L.lock();
                long w = System.nanoTime() - t0;
                spinUs(200);
                L.unlock();
                cycles.incrementAndGet();
                waitNs.addAndGet(w);
                waitMax.accumulateAndGet(w, Math::max);
                sleepMs(10);
            }
        });
        for (int tick = 1;; tick++) {
            Thread.sleep(100);
            fault = Files.exists(Paths.get(flag));
            if (tick % 10 != 0) continue;
            long n = cycles.getAndSet(0), w = waitNs.getAndSet(0), mx = waitMax.getAndSet(0);
            System.out.printf("stats high_cycles=%d high_wait_avg_ms=%.3f high_wait_max_ms=%.3f fault=%d%n",
                    n, n > 0 ? w / 1e6 / n : 0.0, mx / 1e6, fault ? 1 : 0);
        }
    }
}
