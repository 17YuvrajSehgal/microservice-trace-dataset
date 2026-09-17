# 17-09-2026 — decisions

## 1. Built a Train Ticket VM and re-collected the two families the audit could not rescue

`stratatrace-tt`, n2-standard-16, us-east1-d — same shape as v1's TT box, and the same kernel
(7.0.0-1011-gcp) as the Sock Shop VM so the tracer version is not a confound.

Gate passed on first attempt: trace 141 spans, logs 33,357 lines (258 with trace_id), load 406
requests, metrics 1,692 series, **kernel 20,245,693 events**, clocks drift **0.002 ms**.

One bootstrap bug worth fixing: the final step builds the workload image and dies with
`permission denied ... docker.sock`, because the script runs `usermod -aG docker` on *itself* and
group membership does not apply to the session that set it. Re-running the one script in a fresh
session works. Same class as the `arm`-before-tracing ordering bug.

## 2. `error_storm` — the target was wrong, not the intensity

8 fresh runs: **7 borderline, 1 unconfirmed, zero confirmed**, on both steady and burst. So the
weakness is reproducible, and the original family's 6/8 confirmed was **load-dependent luck**.

Checked for a better metric instead of assuming: TT's Spring services expose no actuator
Prometheus endpoint (so no 5xx series like Sock Shop's), `node_netstat_Tcp_OutRsts` reads 0 for
whole runs because node-exporter is containerised and reports its own netns, and the other TCP
reset counters are not captured at all.

**The evidence is in the logs, as the recipe pre-registered.** 462 `Communications link failure`,
1078 `SQLException`, 316 `Connection reset`, 216 `CommunicationsException` — first line at
03:37:32.808Z against an injection start of 03:37:32Z. A `svc_net` run on the same stack counts
**0**, so the signal is specific to the fault rather than to the deployment.

Marked `expected_to_fail`. **Deliberately did not raise the intensity** — that would push a weak
proxy over a threshold while the fault already works, making the number look better and the
dataset worse.

## 3. `svc_net` — I was wrong twice, and the measurements corrected me

First I said it probably did not need re-collecting, because netem provably drops 4.2% on this
VM and `ts-basic-service` carries 18,340 packets per 25 s — so "0% loss" looked like an
instrument problem. Re-analysing the old traces killed that: the tool reproduced r1's **42.9%
retransmission exactly**, so it works on TT traces, and r2/r3/r5 genuinely contain no loss.

What differs is how much work the app did — r1 logged 2341 MB and saw **27 active interfaces**;
r2/r3/r5 logged ~7.5 MB and saw **11**. There was nothing flowing for netem to drop. Identical
ground truth in all five.

So the driver now **aborts** unless the target is measurably on the request path. That check is
what the original campaign lacked.

## 4. The pattern, now five families deep

`fd_exhaustion`, `svc_cpu_cap`, `svc_mem_cap`, `slow_db`, `error_storm` — in every case the
**verification target was wrong, not the fault**. The common flaw: targets measure *consequences*
(throughput, CPU usage, byte rates), which scale with offered load. Mechanisms do not.

Where a mechanism metric exists the fix is total — `container_spec_cpu_quota` took `svc_cpu_cap`
from 0/8 to 8/8. Where none exists on that application, `no_metric_signature` is the honest
answer and the trace or logs carry the evidence.

**This belongs in the paper.** It is a measured, repeated result about what the metrics modality
can and cannot see, which is exactly what the ablation study is for.
