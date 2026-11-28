// deadlock (C, pthreads). See ../problem.sh.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t A = PTHREAD_MUTEX_INITIALIZER, B = PTHREAD_MUTEX_INITIALIZER;
static atomic_long done;

static void spin_us(long us) {
    struct timespec t0, t;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    do clock_gettime(CLOCK_MONOTONIC, &t);
    while ((t.tv_sec - t0.tv_sec) * 1000000L + (t.tv_nsec - t0.tv_nsec) / 1000 < us);
}

static void *worker(void *arg) {
    for (;;) {
        pthread_mutex_lock(&A);
        pthread_mutex_lock(&B);
        spin_us(50);
        pthread_mutex_unlock(&B);
        pthread_mutex_unlock(&A);
        atomic_fetch_add(&done, 1);
        usleep(1000);
    }
    return NULL;
}

static void *wrong_order(void *arg) {     // the fault: B first, then A
    for (;;) {
        pthread_mutex_lock(&B);
        usleep(1000);
        pthread_mutex_lock(&A);
        spin_us(50);
        pthread_mutex_unlock(&A);
        pthread_mutex_unlock(&B);
        usleep(1000);
    }
    return NULL;
}

int main(void) {
    const char *flag = getenv("V4_FLAG") ? getenv("V4_FLAG") : "/dev/shm/v4_fault";
    pthread_t t;
    for (int i = 0; i < 8; i++) {
        pthread_create(&t, NULL, worker, NULL);
        pthread_setname_np(t, "dl_worker");
    }
    int started = 0;
    for (;;) {
        sleep(1);
        if (!started && access(flag, F_OK) == 0) {
            pthread_create(&t, NULL, wrong_order, NULL);
            pthread_setname_np(t, "dl_wrong_order");
            started = 1;
        }
        printf("stats done=%ld wrong_order=%d\n", atomic_exchange(&done, 0), started);
        fflush(stdout);
    }
}
