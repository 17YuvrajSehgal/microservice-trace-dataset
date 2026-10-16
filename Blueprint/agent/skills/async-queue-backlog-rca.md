---
name: async-queue-backlog-rca
version: 1
authored_by: human
covers: queue_backlog
user_triggers: queue growing | consumer lagging | messages piling up | backlog
---
## Problem signature
- the SILENT fault: user-facing latency and error rates look near-NORMAL (async path —
  users don't wait on it); do not expect a loud symptom.
- kernel: the queue CONSUMER's activity drops or goes idle-flavored (sys_futex/poll
  waits up, processing syscalls down) while the message BROKER's net_bytes/net_events
  stay high or grow — traffic enters, little leaves.
- metrics: asymmetry around the broker: producer-side net_tx steady, consumer-side
  processing (cpu, net) falling; queue-ish containers' memory may creep up.
- topology/traces: the async segment disappears from traces or its consumer span rate
  drops; synchronous paths unaffected.

## Investigation blueprint
1. Notice the ABSENCE: if survey shows little user-facing change, hunt async parts —
   brokers/queues/workers (components with net traffic but no synchronous edges).
2. query_kernel on broker + consumer candidates: consumer gone quiet (futex/poll wait,
   reduced work) while broker still receives — the decisive asymmetry.
3. query_metrics on both: throughput in vs work out; memory creep on the broker.
4. query_traces: consumer-side span rate drop vs baseline.

## Resolution template
- fault_type queue_backlog: an async queue/consumer silently backs up — producer
  healthy, consumer idle/lagging, backlog growing, few user-visible errors.
- dependency_outage instead when synchronous callers HANG on the component (not async).
- normal instead only if consumer throughput and broker levels are genuinely unchanged.
Root cause service = the lagging CONSUMER (or the broker if the consumer is healthy but
the broker stopped delivering).
