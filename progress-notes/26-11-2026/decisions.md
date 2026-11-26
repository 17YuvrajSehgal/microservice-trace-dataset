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
