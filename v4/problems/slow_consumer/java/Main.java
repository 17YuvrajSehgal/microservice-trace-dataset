// slow_consumer (Java, LinkedBlockingQueue). See ../problem.sh.
import java.nio.file.*;
import java.util.Arrays;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.LockSupport;

public class Main {
    record Item(long t, byte[] data) { }
    static volatile boolean fault = false;
    static final AtomicLong consumed = new AtomicLong(), ageMax = new AtomicLong();

    public static void main(String[] args) throws Exception {
        String flag = System.getenv().getOrDefault("V4_FLAG", "/dev/shm/v4_fault");
        LinkedBlockingQueue<Item> q = new LinkedBlockingQueue<>();
        Thread p = new Thread(() -> {             // producer: one 8 KB item every 2 ms
            long next = System.nanoTime();
            for (;;) {
                next += 2_000_000L;
                long d;
                while ((d = next - System.nanoTime()) > 0) LockSupport.parkNanos(d);
                byte[] b = new byte[8192];
                Arrays.fill(b, (byte) 7);
                q.add(new Item(System.nanoTime(), b));
            }
        }, "sc_producer");
        Thread c = new Thread(() -> {             // consumer
            for (;;) {
                Item it;
                try { it = q.take(); } catch (InterruptedException e) { continue; }
                long age = System.nanoTime() - it.t();
                if (fault) { try { Thread.sleep(3); } catch (InterruptedException e) { } }
                else { long t0 = System.nanoTime(); while (System.nanoTime() - t0 < 1_000_000L) { } }
                consumed.incrementAndGet();
                ageMax.accumulateAndGet(age, Math::max);
            }
        }, "sc_consumer");
        p.setDaemon(true); c.setDaemon(true);
        p.start(); c.start();
        for (int tick = 1;; tick++) {
            Thread.sleep(100);
            fault = Files.exists(Paths.get(flag));
            if (tick % 10 != 0) continue;
            System.out.printf("stats consumed=%d queue_len=%d item_age_ms=%.3f fault=%d%n",
                    consumed.getAndSet(0), q.size(), ageMax.getAndSet(0) / 1e6, fault ? 1 : 0);
        }
    }
}
