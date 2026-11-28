# 28-11-2026 decisions

## Group 8 (step 3 of the plan: new families)

- **Planned E5, E7, E8, E11, H4. Measured on the VM first; three did not fit Sock Shop:**
  - E7 database deadlock: no service writes to MySQL (the catalogue only reads), and MongoDB has no lock-order deadlock. Moved to the Train Ticket list.
  - E8 slow consumer: 3 shipping messages per 20 s; slowing each needs a `queue-master` code change, and there is no fork. Parked.
  - H4 I/O stall: writes are acknowledged before the disk (the same finding as `io_cap`). Parked with `io_cap`.
- **Replaced with F7 unbounded queue (front-end defect) and G5 SYN flood.** Both fit, with no start-up change.
- **Calibration:**
  - `slow_query`: user p95 4.8 to 20 ms, user-db CPU 5 to 35%.
  - `syn_flood`: 12,000 SYN cookies per second, half-open queue full; users barely notice, so it is a kernel-only family.
  - `code_unbounded_queue` at 200/s: front-end p50 47 to 130 ms; memory flat. The registered "memory rising" was wrong: 150 users wait for answers, so the queue cannot grow without limit. A real unbounded queue needs an open-loop load.
  - `code_rate_limit`: the list path gets only about 30 to 46 requests per second, so 60 and 120 did nothing; 8 per second rejects 30 to 39 per second.
- **Bug found and fixed:** the rejections came back as 500, because go-kit 0.4 wraps the service's error, so the encoder never matched. Now matched on the message; the catalogue image is `v7`. The stock catalogue's own 404 mapping has the same flaw and never fires; left as it is (upstream behaviour).
- **SYN flood safety:** the fake source is an unused address on the service's own Docker network, so no packet leaves the VM. Checked before each start.
- **Issue 28 (new, decision pending):** MongoDB collections grow every run, and orders and carts have no index for their lookup (a 48,000-document scan, 27 ms under load). Nothing changed, to stay comparable with the 149 v3 runs. Options are in CAMPAIGN-ISSUES.
- **Laptop memory:** Claude Code keeps killing the local watchers. The chains run on the VM and shut it down themselves, so nothing is lost; status is checked by hand.

## Group 8 collected and on Trillium

- 20 runs, all checks passed, no lost events; on Trillium with 0 checksum errors; deleted on the VM; VM stopped.
- `code_rate_limit` was re-collected in full after its first check run failed on the 429-only target (the circuit breaker).
- `syn_flood` DOES move the front-end's p95 under tracing (+30 to +75 ms in all 5 runs), while the calibration without tracing showed +4 to +16 ms. The "no metric signature" note was wrong and is corrected in the target. This is the second family that is harsher under tracing (after `code_ctxswitch_storm`); both add many kernel events per second. Worth a line in the paper's threats to validity.
- v3 Sock Shop now has 32 families (160 aggressive runs plus 9 subtle). 20 candidates are not started, 7 of them ready.
