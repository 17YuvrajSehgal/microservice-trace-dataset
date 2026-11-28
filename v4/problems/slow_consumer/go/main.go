// slow_consumer (Go, a buffered channel as the queue). See ../problem.sh.
package main

import (
	"fmt"
	"os"
	"sync/atomic"
	"time"
)

type item struct {
	t    time.Time
	data []byte
}

var fault int32
var consumed, ageMax int64

func main() {
	flag := os.Getenv("V4_FLAG")
	if flag == "" {
		flag = "/dev/shm/v4_fault"
	}
	q := make(chan item, 1<<20)
	go func() { // producer: one 8 KB item every 2 ms
		next := time.Now()
		for {
			next = next.Add(2 * time.Millisecond)
			time.Sleep(time.Until(next))
			d := make([]byte, 8192)
			for i := range d {
				d[i] = 7
			}
			q <- item{time.Now(), d}
		}
	}()
	go func() { // consumer
		for it := range q {
			age := int64(time.Since(it.t))
			if atomic.LoadInt32(&fault) == 1 {
				time.Sleep(3 * time.Millisecond)
			} else {
				t0 := time.Now()
				for time.Since(t0) < time.Millisecond {
				}
			}
			atomic.AddInt64(&consumed, 1)
			for {
				x := atomic.LoadInt64(&ageMax)
				if age <= x || atomic.CompareAndSwapInt64(&ageMax, x, age) {
					break
				}
			}
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
		fmt.Printf("stats consumed=%d queue_len=%d item_age_ms=%.3f fault=%d\n", atomic.SwapInt64(&consumed, 0), len(q),
			float64(atomic.SwapInt64(&ageMax, 0))/1e6, atomic.LoadInt32(&fault))
	}
}
