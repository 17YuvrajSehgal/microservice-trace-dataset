// lock_contention (C, pthreads). See ../problem.sh.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t M = PTHREAD_MUTEX_INITIALIZER;
static atomic_int fault;
static atomic_long done, wait_ns, wait_max_ns;

static long now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000000000L + t.tv_nsec;
}
static void spin_us(long us) {
    long t0 = now_ns();
    while (now_ns() - t0 < us * 1000) { }
}

static void *worker(void *arg) {
    for (;;) {
        long t0 = now_ns();
        pthread_mutex_lock(&M);
        long w = now_ns() - t0;
        spin_us(atomic_load(&fault) ? 2000 : 20);
        pthread_mutex_unlock(&M);
        atomic_fetch_add(&done, 1);
        atomic_fetch_add(&wait_ns, w);
        long m = atomic_load(&wait_max_ns);
        while (w > m && !atomic_compare_exchange_weak(&wait_max_ns, &m, w)) { }
        usleep(1000);
    }
    return NULL;
}

int main(void) {
    const char *flag = getenv("V4_FLAG") ? getenv("V4_FLAG") : "/dev/shm/v4_fault";
    pthread_t t;
    for (int i = 0; i < 16; i++) {
        pthread_create(&t, NULL, worker, NULL);
        pthread_setname_np(t, "lc_worker");
    }
    for (int tick = 1;; tick++) {
        usleep(100000);
        atomic_store(&fault, access(flag, F_OK) == 0);
        if (tick % 10) continue;
        long n = atomic_exchange(&done, 0), w = atomic_exchange(&wait_ns, 0), mx = atomic_exchange(&wait_max_ns, 0);
        printf("stats done=%ld wait_avg_ms=%.3f wait_max_ms=%.3f fault=%d\n", n, n ? w / 1e6 / n : 0.0, mx / 1e6, atomic_load(&fault));
        fflush(stdout);
    }
}
