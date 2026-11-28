// deadlock (Java, ReentrantLock). See ../problem.sh.
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

public class Main {
    static final ReentrantLock A = new ReentrantLock(), B = new ReentrantLock();
    static final AtomicLong done = new AtomicLong();

    static void spinUs(long us) {
        long t0 = System.nanoTime();
        while (System.nanoTime() - t0 < us * 1000) { }
    }

    static void sleepMs(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { }
    }

    public static void main(String[] args) {
        String flag = System.getenv().getOrDefault("V4_FLAG", "/dev/shm/v4_fault");
        for (int i = 0; i < 8; i++) {
            Thread t = new Thread(() -> {
                for (;;) {
                    A.lock(); B.lock();
                    spinUs(50);
                    B.unlock(); A.unlock();
                    done.incrementAndGet();
                    sleepMs(1);
                }
            }, "dl_worker");
            t.setDaemon(true);
            t.start();
        }
        int started = 0;
        for (;;) {
            sleepMs(1000);
            if (started == 0 && Files.exists(Paths.get(flag))) {
                Thread w = new Thread(() -> {       // the fault: B first, then A
                    for (;;) {
                        B.lock(); sleepMs(1); A.lock();
                        spinUs(50);
                        A.unlock(); B.unlock();
                        sleepMs(1);
                    }
                }, "dl_wrong_order");
                w.setDaemon(true);
                w.start();
                started = 1;
            }
            System.out.println("stats done=" + done.getAndSet(0) + " wrong_order=" + started);
        }
    }
}
