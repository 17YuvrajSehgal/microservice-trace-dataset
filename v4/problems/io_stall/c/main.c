// io_stall (C): append 4 KB and fsync every 5 ms, reporting how long each write+fsync took.
// See ../problem.sh.
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static long now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000000000L + t.tv_nsec; }

int main(void) {
    int fd = open("/mnt/v4io/c.dat", O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) { perror("open"); return 1; }
    char buf[4096];
    memset(buf, 'x', sizeof buf);
    long ops = 0, sum = 0, mx = 0, next = now_ns(), report = next + 1000000000L;
    for (;;) {
        long t0 = now_ns();
        if (write(fd, buf, sizeof buf) < 0 || fsync(fd) < 0) perror("write");
        long d = now_ns() - t0;
        ops++; sum += d; if (d > mx) mx = d;
        if (now_ns() >= report) {
            printf("stats ops=%ld op_avg_ms=%.3f op_max_ms=%.3f\n", ops, ops ? sum / 1e6 / ops : 0.0, mx / 1e6);
            fflush(stdout);
            ops = sum = mx = 0;
            report += 1000000000L;
            if (now_ns() > report) report = now_ns() + 1000000000L;
        }
        next += 5000000L;
        if (now_ns() > next) next = now_ns();
        struct timespec ts = {next / 1000000000L, next % 1000000000L};
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
    }
}
