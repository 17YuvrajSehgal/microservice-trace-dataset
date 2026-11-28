// priority_inversion (C, pthreads; the mutex has no priority inheritance). See ../problem.sh.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t L = PTHREAD_MUTEX_INITIALIZER;
static atomic_int fault;
static atomic_long cycles, wait_ns, wait_max_ns;

static long now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000000000L + t.tv_nsec;
}
static void spin_us(long us) { long t0 = now_ns(); while (now_ns() - t0 < us * 1000) { } }
static void report_tid(const char *role) {
    char line[64];
    snprintf(line, sizeof line, "%s %ld\n", role, (long)syscall(SYS_gettid));
    FILE *f = fopen(getenv("V4_TIDS") ? getenv("V4_TIDS") : "/dev/shm/v4_tids", "a");
    if (f) { fputs(line, f); fclose(f); }
    pthread_setname_np(pthread_self(), role);
}

static void *low(void *a) {
    report_tid("low");
    for (;;) { pthread_mutex_lock(&L); spin_us(5000); pthread_mutex_unlock(&L); usleep(15000); }
}
static void *mid(void *a) {
    report_tid((const char *)a);
    for (;;) {
        if (atomic_load(&fault)) { spin_us(50000); usleep(2000); }
        else usleep(100000);
    }
}
static void *high(void *a) {
    report_tid("high");
    for (;;) {
        long t0 = now_ns();
        pthread_mutex_lock(&L);
        long w = now_ns() - t0;
        spin_us(200);
        pthread_mutex_unlock(&L);
        atomic_fetch_add(&cycles, 1);
        atomic_fetch_add(&wait_ns, w);
        long m = atomic_load(&wait_max_ns);
        while (w > m && !atomic_compare_exchange_weak(&wait_max_ns, &m, w)) { }
        usleep(10000);
    }
}

int main(void) {
    const char *flag = getenv("V4_FLAG") ? getenv("V4_FLAG") : "/dev/shm/v4_fault";
    pthread_t t;
    pthread_create(&t, NULL, low, NULL);
    pthread_create(&t, NULL, mid, "mid1");
    pthread_create(&t, NULL, mid, "mid2");
    pthread_create(&t, NULL, high, NULL);
    for (int tick = 1;; tick++) {
        usleep(100000);
        atomic_store(&fault, access(flag, F_OK) == 0);
        if (tick % 10) continue;
        long n = atomic_exchange(&cycles, 0), w = atomic_exchange(&wait_ns, 0), mx = atomic_exchange(&wait_max_ns, 0);
        printf("stats high_cycles=%ld high_wait_avg_ms=%.3f high_wait_max_ms=%.3f fault=%d\n", n, n ? w / 1e6 / n : 0.0, mx / 1e6, atomic_load(&fault));
        fflush(stdout);
    }
}
