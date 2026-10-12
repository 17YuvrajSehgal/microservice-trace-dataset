#### What is Latency
Latency is the time a request waits before it gets its answer. But the request passes through many steps, so during the RCA, we need to find the part that grew the most – and causes latency.

If a request waits longer than its timeout, it fails. So a very slow system can also show errors. This is why a latency problem and an error problem can look alike at first.

Latency is different from the following terms:
- Throughput: How many requests the system finishes per second. A system can have high throughput and bad latency at the same time.

- Bandwidth: How much data the network can carry per second.

- Response Time: Almost the same as latency. Sometimes we count the wait in the queue – how much time before the request gets its answer.

We cannot rely on average to find the latency. Because let's say if we are testing 100 requests, out of which 95 take 100 ms to finish, whereas the remaining 5 requests take 3000 ms to finish. The average would be (9500+15000)/100 = 245 ms, which is not the actual latency and can mislead us.


Instead, we will use percentiles.
- p50 (median): half of the requests are faster than this. Here it is 100 ms.
- p95: 95% of the requests are faster than this.
- p99: 99% of the requests are faster than this. Here it is 3000 ms.

The slow end is called tail latency -> many faults show up only in the tail.

The key idea is the time budget. A thread is in one of the three states:
- Running: It is using the CPU.
  - Where we might see it:
    - Slow code, like a loop that is too big.
    - Too many small database calls (N+1).
    - Calls made one after another when they could run in parallel.
    
- Runnable: It wants the CPU but is waiting for its turn.
  - Where we might see it:
    - Another process is using the CPU (noisy neighbor).
    - A CPU cap limits the container.
    - Too many processes at once (fork storm).
    
- Blocked: It is waiting for something, like disk, network, or a lock.
  - Where we might see it:
    - Disk: Slow reads and writes.
    - Network: Delay or lost packets.
    - Lock: Another thread holds it.
    - Remote service: A database or API is slow.
    - Connection pool: All connections are in use.
    - DNS: The name lookup is slow.