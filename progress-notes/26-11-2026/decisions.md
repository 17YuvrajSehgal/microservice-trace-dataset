# 26 Nov 2026 - decisions

## Full log sweep, 363 runs (login node, no model): `Blueprint/logkit/RESULTS.md`

- Held-out Sock Shop (167 fault runs, 30 families): **0 false alarms**; on-time onset in 13
  families. Train Ticket (124 fault runs, 10 normal): **2 false alarms**, onset in 6 of 20
  families only; its Java services log far less that a tool can use.
- **Line-rate drop stays a NOTE** (decided): on all 10 healthy Train Ticket runs a busy service
  drops when a load phase ends.
- **log_window's 20 s baseline is fooled by a warning that comes every 30 s** (ts-travel-service,
  every TT fault run). Not fixed: the fix would be tuned on the held-out runs. log_onset is not
  fooled (its baseline is the run's first 40 s).
- The safety check first refused all of Train Ticket (a service is called
  ts-verification-code-service). Now it matches label files at the start of a name only.

## Logs narrow where to look (user's point), measured on the full sweep

- A second job for logs beside early warning: when the agent has no suspect, a shortlist of
  services and the kinds of fault to try first (LOGS-PLAN 6.5).
- The flagged service is usually the CALLER of the culprit. On 102 Sock Shop single-target runs:
  culprit among the flagged 44; among the flagged plus what they call **98**, median shortlist 6 of
  ~15 containers. Call graph from Sock Shop's wiring for now; it should come from the run's spans
  (or the kernel's TCP connections where there are no spans).
- Silent logs are also a hint: they point to the resource and scheduling faults. A priority,
  never a reason to rule a blueprint out.

## Call graph from spans (`Blueprint/spankit`) and the measured shortlist

- Edges by **span link first** (the callee's span names the caller's span as parent), then the
  peer name in the caller's span, then the IP. Why: Train Ticket calls by IP through its
  registry; only the link names those callees. Each edge also keeps the db.system its spans name,
  so a proxy (toxiproxy) still points at its database (mysql).
- Blind spots are written into the graph (services with no spans; traced services with no
  outgoing span) and printed as "unknown", never "none".
- Shortlist (flagged + what they call): Sock Shop **67 of 102** (estimate with hand wiring was
  98), Train Ticket **21 of 26** from 46 entities. All 35 Sock Shop misses are the two blind
  spots (catalogue -> catalogue-db, edge-router). Next source of edges: kernel TCP connections.
