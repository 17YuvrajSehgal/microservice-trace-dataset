// priority_inversion (Go). Each role runs on its own OS thread (runtime.LockOSThread), so the
// runner can give that thread a real-time priority. sync.Mutex has no priority inheritance.
// See ../problem.sh.
package main

import (
	"fmt"
	"os"
	"runtime"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

var l sync.Mutex
var fault int32
var cycles, waitNs, waitMax int64

func spin(d time.Duration) {
	t0 := time.Now()
	for time.Since(t0) < d {
	}
}

func role(name string) {
	runtime.LockOSThread()
	path := os.Getenv("V4_TIDS")
	if path == "" {
		path = "/dev/shm/v4_tids"
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		fmt.Fprintf(f, "%s %d\n", name, syscall.Gettid())
		f.Close()
	}
}

func main() {
	flag := os.Getenv("V4_FLAG")
	if flag == "" {
		flag = "/dev/shm/v4_fault"
	}
	go func() {
		role("low")
		for {
			l.Lock()
			spin(5 * time.Millisecond)
			l.Unlock()
			time.Sleep(15 * time.Millisecond)
		}
	}()
	for _, n := range []string{"mid1", "mid2"} {
		go func(n string) {
			role(n)
			for {
				if atomic.LoadInt32(&fault) == 1 {
					spin(50 * time.Millisecond)
					time.Sleep(2 * time.Millisecond)
				} else {
					time.Sleep(100 * time.Millisecond)
				}
			}
		}(n)
	}
	go func() {
		role("high")
		for {
			t0 := time.Now()
			l.Lock()
			w := int64(time.Since(t0))
			spin(200 * time.Microsecond)
			l.Unlock()
			atomic.AddInt64(&cycles, 1)
			atomic.AddInt64(&waitNs, w)
			for {
				x := atomic.LoadInt64(&waitMax)
				if w <= x || atomic.CompareAndSwapInt64(&waitMax, x, w) {
					break
				}
			}
			time.Sleep(10 * time.Millisecond)
		}
	}()
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
		n, w, mx := atomic.SwapInt64(&cycles, 0), atomic.SwapInt64(&waitNs, 0), atomic.SwapInt64(&waitMax, 0)
		avg := 0.0
		if n > 0 {
			avg = float64(w) / 1e6 / float64(n)
		}
		fmt.Printf("stats high_cycles=%d high_wait_avg_ms=%.3f high_wait_max_ms=%.3f fault=%d\n", n, avg, float64(mx)/1e6, atomic.LoadInt32(&fault))
	}
}
