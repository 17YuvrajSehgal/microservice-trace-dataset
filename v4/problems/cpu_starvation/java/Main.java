// cpu_starvation (Java): a 10 ms periodic task with 1 ms of work, reporting its wake-up lateness.
// See ../problem.sh.
import java.util.Arrays;
import java.util.concurrent.locks.LockSupport;

public class Main {
    public static void main(String[] args) {
        long[] late = new long[400];
        int n = 0;
        long next = System.nanoTime(), report = next + 1_000_000_000L;
        for (;;) {
            next += 10_000_000L;
            long d;
            while ((d = next - System.nanoTime()) > 0) LockSupport.parkNanos(d);
            long t = System.nanoTime();
            if (n < late.length) late[n++] = t - next;
            while (System.nanoTime() - t < 1_000_000L) { }        // 1 ms of work
            if (t >= report) {
                long[] s = Arrays.copyOf(late, n);
                Arrays.sort(s);
                System.out.printf("stats ticks=%d late_p50_ms=%.3f late_p99_ms=%.3f late_max_ms=%.3f%n",
                        n, s[n / 2] / 1e6, s[n * 99 / 100] / 1e6, s[n - 1] / 1e6);
                n = 0;
                report += 1_000_000_000L;
            }
            if (System.nanoTime() > next + 10_000_000L) next = System.nanoTime();
        }
    }
}
