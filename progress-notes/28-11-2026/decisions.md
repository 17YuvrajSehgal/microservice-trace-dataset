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

## Blueprints 53 to 56 (group 8)

- **Result on all 70 runs of groups 5 to 8, forward and reversed:** every tool finds its own family 5 of 5, with 0 false alarms on the other 65 and 0 of 70 reversed. One exception: `log_errors.py` also fires on `dns_delay_jvm` (a different, real error message); the blueprint judges by the second tool.
- **New tools:** `slow_answers` (53), `breaker_cause` (54), `paced_calls` (55), `half_open` (56). `log_errors` reused unchanged.
- **Changed after seeing data, written in each tool and RESULTS:**
  - `slow_answers` and `paced_calls`: the server of a connection is the side with a port below 32768. The first version took the first sender in the slice as the client, and on connections already open that is often the server. This flaw was in my new code only, not in `call_fanout.py`.
  - `slow_answers`: median may rise by at most 25%, to keep load shifts out.
  - `paced_calls`: the clock is looked for from 4 ms and must be a bump.
  - `breaker_cause`: bars set after seeing the 10 runs it separates (`code_rate_limit` and `mtu_blackhole`). A fit, not a test.
- **Unchanged from first setting:** `half_open` (cleanest result), `log_errors`.
- **Finding:** "too many requests" is also gobreaker's half-open answer, so the message alone cannot prove a rate limit; the absence of dependency errors does. My 429 mapping also catches those half-open answers (noted for the paper's description of the family).
- **Pattern:** in `slow_query` the knock-on service shows as "the server waits" and the root as "the server works longer". This is a good example for the agent's step of picking the root among several verdicts.

## v4: the controlled tier (user's idea, agreed today)

- **What:** small programs with one problem each, in C, Go, Java, Python and Node.js, run on the VM's host (Sock Shop stopped) and traced with exactly the v3 kernel profile. Every run has the same background noise (a web server and client, gzip, sha256sum), and every problem and language has a healthy twin. Code in `v4/`.
- **Why two tiers:** v4 gives fast, varied, labelled runs, and the problems Sock Shop cannot make (deadlock, slow consumer, I/O stall), plus labelled data for the bare-metal blueprints 8 to 11. Sock Shop and Train Ticket stay the realistic tier. The noise and the healthy twins answer "toy programs".
- **Pilot:** deadlock, lock_contention, priority_inversion, cpu_starvation, slow_consumer, io_stall. 28 problem-and-language pairs, 3 fault runs and 1 healthy twin each (112 runs, about 7.5 h). Predictions registered before the first collection run.
- **The smoke test (short runs, not in the dataset) found:**
  - Priority inversion: pinning the whole program to one CPU starved its own reporting thread; now only the 4 role threads are pinned.
  - Priority inversion does not form in Python (the interpreter lock decides who runs). Python is left out of that problem; a real runtime difference.
  - Lock contention in Python moves the waiting to the interpreter lock; it is checked on work done.
  - I/O stall: the freezes work (about 2,035 ms writes once every 6 s), but a median check cannot see them; it now uses the 90th percentile.
  - One short run is 25 to 70 MB packed; a full run should be about 75 to 200 MB, so the pilot is about 15 GB in total.
- **Next after the pilot:** run the existing blueprints on it first (deadlock 14, priority inversion 11, CPU starvation 8, lock tools), then v4 versions of the families already collected, as the user asked, to test the blueprints' robustness.
