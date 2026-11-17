# Blueprint 23 results (tool only, 17-11-2026)

`call_fanout.py` on every v2 run of both applications (304), 20 s `net_dev_queue` slices.
Two SLURM jobs on Trillium, one node each:

- job 2879871 (21 min): fault slice 30 s after the injection, baseline 40 s before it.
- job 2880078 (22 min): the same fault slice, reference 25 s after the injection ends
  (normal runs: 130 s and 60 s after the trace start in both jobs).

Outputs: `work/dx_check/sweep_cd/`, `work/dx_check/sweep_cd2/`. The final rule (1.35 times,
answers at most 1.1 times slower, 200 calls out and 200 requests in) was applied to the
saved tables of both jobs; the jobs themselves ran with a bar of 3 times and printed every row.

## Reference after the fault (steady load), job 2880078

| runs | result | catalogue -> database, calls per request |
|---|---|---|
| `code_n_plus_one`, 5 + the proof run | CALL AMPLIFICATION, 6 of 6 | 3.15-3.83 against 2.10-2.65 (1.45-1.57 times), answers 0.76-0.86 times as long |
| other runs that could be judged, 175 (145 Sock Shop, 30 Train Ticket) | none | highest pair: 1.28 times (`error_storm` burst, a Java service -> its MongoDB); `normal`: at most 1.19 |
| not judged, 123 | no pair with 200 calls and 200 received requests in both slices | 104 Train Ticket runs, 19 Sock Shop runs; 3 of them are failed slice cuts |

Rows that reach 1.35 times and are rejected by the other conditions:

| rows | why rejected |
|---|---|
| edge-router -> front-end, 1.30-2.45 times (`anomaly_cpu`, `anomaly_mem`, `noisy_neighbor`, `nagle_delayed_ack`, `lock_contention`) | the edge-router receives under 200 requests in the slice by this count; in most of them the answers are also 1.2-3.0 times slower |
| front-end -> user, 1.42-1.58 times (`anomaly_net` burst) | answers 400 times slower (packet loss); 11-14 calls/s |
| Train Ticket service -> database proxy, 1.43-1.54 times (`tt_svc_net`) | under 200 received requests |

## Baseline before the fault (load ramp-up), job 2879871

Not usable. The same catalogue pair is at 1.49-1.58 times in the fault runs and at most 1.23
in other families, but a Java service -> its MongoDB rises 1.58-1.65 times in many unrelated runs
(`anomaly_mem`, `error_storm`, `conn_pool_exhaustion`, `lock_contention`, `deadlock`,
`slow_db`), with answers not slower. In the `normal` runs, where both slices are at steady
load, the largest rise of any pair is 1.01-1.19.

## `code_lock_across_io`: no signal (measured in the same jobs)

The catalogue holds a lock across its list query. Nothing separates the 5 runs from `normal`:

| catalogue -> database | `code_lock_across_io` | `normal` |
|---|---|---|
| calls per request, fault against reference | 0.97-1.01 times | 0.98-1.04 times |
| time per answer | 0.41-0.47 ms | 0.49-0.55 ms |
| share of the slice with 2 or more calls in flight | 61.9-66.1% (65.7-67.7% before) | 73.1-97.6% |
| `futex` calls by the catalogue, fault against reference | 0.98-1.03 times | 0.95-1.05 times |

So at this load the lock is not contended enough to show. No blueprint was written.
