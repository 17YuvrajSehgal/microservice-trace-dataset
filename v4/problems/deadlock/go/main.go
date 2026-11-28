// deadlock (Go, sync.Mutex). See ../problem.sh.
// Goroutines are not threads: a goroutine that waits on a sync.Mutex is parked by the Go runtime,
// and the OS threads underneath go idle. That is part of what v4 measures across languages.
package main

import (
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

var a, b sync.Mutex
var done int64

func spin(d time.Duration) {
	t0 := time.Now()
	for time.Since(t0) < d {
	}
}

func worker() {
	for {
		a.Lock()
		b.Lock()
		spin(50 * time.Microsecond)
		b.Unlock()
		a.Unlock()
		atomic.AddInt64(&done, 1)
		time.Sleep(time.Millisecond)
	}
}

func wrongOrder() { // the fault: B first, then A
	for {
		b.Lock()
		time.Sleep(time.Millisecond)
		a.Lock()
		spin(50 * time.Microsecond)
		a.Unlock()
		b.Unlock()
		time.Sleep(time.Millisecond)
	}
}

func main() {
	flag := os.Getenv("V4_FLAG")
	if flag == "" {
		flag = "/dev/shm/v4_fault"
	}
	for i := 0; i < 8; i++ {
		go worker()
	}
	started := 0
	for {
		time.Sleep(time.Second)
		if started == 0 {
			if _, err := os.Stat(flag); err == nil {
				go wrongOrder()
				started = 1
			}
		}
		fmt.Printf("stats done=%d wrong_order=%d\n", atomic.SwapInt64(&done, 0), started)
	}
}
