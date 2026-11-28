// cpu_starvation (Go): a 10 ms periodic task with 1 ms of work, reporting its wake-up lateness.
// See ../problem.sh.
package main

import (
	"fmt"
	"sort"
	"time"
)

func main() {
	var late []time.Duration
	next := time.Now()
	report := next.Add(time.Second)
	for {
		next = next.Add(10 * time.Millisecond)
		time.Sleep(time.Until(next))
		t := time.Now()
		late = append(late, t.Sub(next))
		for time.Since(t) < time.Millisecond { // 1 ms of work
		}
		if t.After(report) {
			sort.Slice(late, func(i, j int) bool { return late[i] < late[j] })
			n := len(late)
			fmt.Printf("stats ticks=%d late_p50_ms=%.3f late_p99_ms=%.3f late_max_ms=%.3f\n", n,
				late[n/2].Seconds()*1e3, late[n*99/100].Seconds()*1e3, late[n-1].Seconds()*1e3)
			late = late[:0]
			report = report.Add(time.Second)
		}
		if time.Since(next) > 10*time.Millisecond {
			next = time.Now()
		}
	}
}
