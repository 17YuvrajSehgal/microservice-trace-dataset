# Next steps

Updated 2026-09-05 (end of the fault-recipe session).

## Done and verified

- **Both VMs are up and bootstrapped.** `stratatrace-ss` (Sock Shop, 21 containers) and
  `stratatrace-tt` (Train Ticket, 49 containers), same zone `us-east1-d`, same LTTng 2.15.
- **Ten new fault recipes pass on both applications**, each with a negative control (every
  check re-run with nothing injected must FAIL): Sock Shop 10/10, Train Ticket 9/9 —
  `dns_delay` is excluded there, measured, see below.
- **Five code defects pass on Sock Shop** against their own `STRATA_BUG=none` control:
  5.14x, 6.14x, 39.98x, 16.41x, plus memory growth.
- **Matrix populated**: 169 Sock Shop + 134 Train Ticket = 303 runs.

## Blocking the campaign

1. **Verification targets for the 15 new faults.** They currently record `no_targets`.
   `faults/measure_targets.sh` is written and needs one calibration pass per app (~1 h each).
   Register only what measurably moves — plausible PromQL would look like verification while
   confirming nothing.
2. **Train Ticket has no seeded data.** Its bootstrap ends with "seed TT data (empty DBs →
   search returns [])". No seeding script exists. `load_generator.py --probe` has never been
   run against this stack.
3. **Pre-registration.** `fault_catalog.md` has cards for F1–F12 only. The 15 new families have
   no pre-registered modality predictions, and predictions freeze when Phase 2 starts. This is
   a research decision, not an implementation one.

## Open decisions

- **Run counts are uneven: 169 vs 134.** The gap is code defects (25, they patch Sock Shop's
  own source), `queue_backlog` (5, no broker in TT), `dns_delay` (5, TT sends no DNS).
  The clean fix for the last is a TT-native member of the same family — impair **Nacos** so
  discovery is slow there in the way DNS is slow here. Not written.
- **Archive disks.** Both VMs have a 1 TB `archive` disk attached; neither appears mounted.
  v1 was 1.19 TB gzipped, which will not fit 1 TB — transfer to Trillium has to be incremental.
- **`AUDIT_KERNEL_TIMEOUT` is deliberately unset.** The kernel step is the only part of the
  audit whose cost scales with the whole trace. Measure it on the first real v2 run and set it
  then; guessing wastes hours or truncates every audit.

## Facts measured this session, worth not rediscovering

| | Sock Shop | Train Ticket |
|---|---|---|
| front-door idle descriptors | 21 | 125 (JVM) |
| MySQL `max_connections` | 151 (5.7) | 2000 (8.0) |
| DNS packets / 400 requests | 54 | **0** (Nacos discovery) |
| compose network | `docker-compose_default` | `trainticket_my-network` |
| `fd_exhaustion` symptom | slows, 0 errors | fails, 357/600 errors |
