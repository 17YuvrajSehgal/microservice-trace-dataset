// io_stall (Java): append 4 KB and force (fsync) every 5 ms, reporting how long each took.
// See ../problem.sh.
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.util.concurrent.locks.LockSupport;

public class Main {
    public static void main(String[] args) throws Exception {
        FileChannel ch = FileChannel.open(Paths.get("/mnt/v4io/java.dat"),
                StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
        byte[] b = new byte[4096];
        java.util.Arrays.fill(b, (byte) 'x');
        long ops = 0, sum = 0, mx = 0, next = System.nanoTime(), report = next + 1_000_000_000L;
        for (;;) {
            long t0 = System.nanoTime();
            ch.write(ByteBuffer.wrap(b));
            ch.force(true);
            long d = System.nanoTime() - t0;
            ops++; sum += d; mx = Math.max(mx, d);
            if (System.nanoTime() >= report) {
                System.out.printf("stats ops=%d op_avg_ms=%.3f op_max_ms=%.3f%n", ops, ops > 0 ? sum / 1e6 / ops : 0.0, mx / 1e6);
                ops = sum = mx = 0;
                report += 1_000_000_000L;
                if (System.nanoTime() > report) report = System.nanoTime() + 1_000_000_000L;
            }
            next += 5_000_000L;
            if (System.nanoTime() > next) next = System.nanoTime();
            long w;
            while ((w = next - System.nanoTime()) > 0) LockSupport.parkNanos(w);
        }
    }
}
