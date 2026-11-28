// cpu_starvation (C): a 10 ms periodic task with 1 ms of work, reporting its wake-up lateness.
// See ../problem.sh.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static long now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000000000L + t.tv_nsec;
}
static int cmp(const void *a, const void *b) { long x = *(long *)a, y = *(long *)b; return (x > y) - (x < y); }

int main(void) {
    long late[200]; int n = 0;
    long next = now_ns(), report = next + 1000000000L;
    for (;;) {
        next += 10000000L;
        struct timespec ts = {next / 1000000000L, next % 1000000000L};
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
        long t = now_ns();
        if (n < 200) late[n++] = t - next;
        while (now_ns() - t < 1000000L) { }                 // 1 ms of work
        if (t >= report) {
            qsort(late, n, sizeof(long), cmp);
            printf("stats ticks=%d late_p50_ms=%.3f late_p99_ms=%.3f late_max_ms=%.3f\n", n, late[n / 2] / 1e6, late[n * 99 / 100] / 1e6, late[n - 1] / 1e6);
            fflush(stdout);
            n = 0;
            report += 1000000000L;
        }
        if (now_ns() > next + 10000000L) next = now_ns();   // fell behind by a whole period: restart the schedule
    }
}
