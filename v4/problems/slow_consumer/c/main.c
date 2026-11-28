// slow_consumer (C, pthreads, a linked-list queue). See ../problem.sh.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef struct item { struct item *next; long t; char data[8192]; } item;
static item *head, *tail;
static long qlen;
static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t c = PTHREAD_COND_INITIALIZER;
static atomic_int fault;
static atomic_long consumed, age_max_ns;

static long now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000000000L + t.tv_nsec; }

static void *producer(void *a) {
    long next = now_ns();
    for (;;) {
        next += 2000000L;
        struct timespec ts = {next / 1000000000L, next % 1000000000L};
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
        item *it = malloc(sizeof(item));
        memset(it->data, 7, sizeof it->data);
        it->t = now_ns(); it->next = NULL;
        pthread_mutex_lock(&m);
        if (tail) tail->next = it; else head = it;
        tail = it; qlen++;
        pthread_cond_signal(&c);
        pthread_mutex_unlock(&m);
    }
}
static void *consumer(void *a) {
    for (;;) {
        pthread_mutex_lock(&m);
        while (!head) pthread_cond_wait(&c, &m);
        item *it = head; head = it->next; if (!head) tail = NULL; qlen--;
        pthread_mutex_unlock(&m);
        long age = now_ns() - it->t;
        if (atomic_load(&fault)) usleep(3000);
        else { long t0 = now_ns(); while (now_ns() - t0 < 1000000L) { } }
        free(it);
        atomic_fetch_add(&consumed, 1);
        long mx = atomic_load(&age_max_ns);
        while (age > mx && !atomic_compare_exchange_weak(&age_max_ns, &mx, age)) { }
    }
}

int main(void) {
    const char *flag = getenv("V4_FLAG") ? getenv("V4_FLAG") : "/dev/shm/v4_fault";
    pthread_t t;
    pthread_create(&t, NULL, producer, NULL); pthread_setname_np(t, "sc_producer");
    pthread_create(&t, NULL, consumer, NULL); pthread_setname_np(t, "sc_consumer");
    for (int tick = 1;; tick++) {
        usleep(100000);
        atomic_store(&fault, access(flag, F_OK) == 0);
        if (tick % 10) continue;
        pthread_mutex_lock(&m); long q = qlen; pthread_mutex_unlock(&m);
        printf("stats consumed=%ld queue_len=%ld item_age_ms=%.3f fault=%d\n", atomic_exchange(&consumed, 0), q, atomic_exchange(&age_max_ns, 0) / 1e6, atomic_load(&fault));
        fflush(stdout);
    }
}
