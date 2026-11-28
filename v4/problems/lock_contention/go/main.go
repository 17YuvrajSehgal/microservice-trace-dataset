// lock_contention (Go, sync.Mutex). See ../problem.sh.
package main

import (
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

var m sync.Mutex
var fault int32
var done, waitNs, waitMax int64

func spin(d time.Duration) {
	t0 := time.Now()
	for time.Since(t0) < d {
	}
}

func worker() {
	for {
		t0 := time.Now()
		m.Lock()
		w := int64(time.Since(t0))
		if atomic.LoadInt32(&fault) == 1 {
			spin(2 * time.Millisecond)
		} else {
			spin(20 * time.Microsecond)
		}
		m.Unlock()
		atomic.AddInt64(&done, 1)
		atomic.AddInt64(&waitNs, w)
		for {
			x := atomic.LoadInt64(&waitMax)
			if w <= x || atomic.CompareAndSwapInt64(&waitMax, x, w) {
				break
			}
		}
		time.Sleep(time.Millisecond)
	}
}

func main() {
	flag := os.Getenv("V4_FLAG")
	if flag == "" {
		flag = "/dev/shm/v4_fault"
	}
	for i := 0; i < 16; i++ {
		go worker()
	}
	for tick := 1; ; tick++ {
		time.Sleep(100 * time.Millisecond)
		if _, err := os.Stat(flag); err == nil {
			atomic.StoreInt32(&fault, 1)
		} else {
			atomic.StoreInt32(&fault, 0)
		}
		if tick%10 != 0 {
			continue
		}
		n, w, mx := atomic.SwapInt64(&done, 0), atomic.SwapInt64(&waitNs, 0), atomic.SwapInt64(&waitMax, 0)
		avg := 0.0
		if n > 0 {
			avg = float64(w) / 1e6 / float64(n)
		}
		fmt.Printf("stats done=%d wait_avg_ms=%.3f wait_max_ms=%.3f fault=%d\n", n, avg, float64(mx)/1e6, atomic.LoadInt32(&fault))
	}
}
