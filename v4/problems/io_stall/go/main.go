// io_stall (Go): append 4 KB and fsync every 5 ms, reporting how long each write+fsync took.
// See ../problem.sh.
package main

import (
	"fmt"
	"os"
	"time"
)

func main() {
	f, err := os.OpenFile("/mnt/v4io/go.dat", os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0644)
	if err != nil {
		fmt.Println("open:", err)
		os.Exit(1)
	}
	buf := make([]byte, 4096)
	for i := range buf {
		buf[i] = 'x'
	}
	var ops int
	var sum, mx time.Duration
	next := time.Now()
	report := next.Add(time.Second)
	for {
		t0 := time.Now()
		f.Write(buf)
		f.Sync()
		d := time.Since(t0)
		ops++
		sum += d
		if d > mx {
			mx = d
		}
		if time.Now().After(report) {
			avg := 0.0
			if ops > 0 {
				avg = sum.Seconds() * 1e3 / float64(ops)
			}
			fmt.Printf("stats ops=%d op_avg_ms=%.3f op_max_ms=%.3f\n", ops, avg, mx.Seconds()*1e3)
			ops, sum, mx = 0, 0, 0
			report = report.Add(time.Second)
			if time.Now().After(report) {
				report = time.Now().Add(time.Second)
			}
		}
		next = next.Add(5 * time.Millisecond)
		if time.Now().After(next) {
			next = time.Now()
		}
		time.Sleep(time.Until(next))
	}
}
