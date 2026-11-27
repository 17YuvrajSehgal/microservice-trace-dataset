# Blueprint 50 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `call_fanout.py --slower-ok` on `code_chatty_calls` (front-end `node` to the catalogue, port 80) |
|---|---|
| r1 | 2.2 calls per request received, 0.6 before (3.5 times); 570 calls per second (227 before); 17.02 ms per answer (1.81 before) |
| r2 | 2.2, 0.6 before (3.5 times); 587 per second (234); 15.48 ms (1.83) |
| r3 | 2.3, 0.6 before (3.6 times); 606 per second (225); 14.88 ms (1.90) |
| r4 | 2.1, 0.6 before (3.5 times); 551 per second (219); 15.79 ms (1.81) |
| r5 | 2.1, 0.6 before (3.4 times); 579 per second (230); 14.76 ms (1.93) |

Quiet on the other 45 runs; reversed quiet in all 50. The largest rise elsewhere, with answers not
slower, was 1.21 times.

The defect makes 3 extra calls per call, so 4 times was expected; the measured rise is 3.4 to 3.6
times, because the overloaded front-end also serves fewer requests.

Changed after run 1: the tool's first rule (blueprint 23) asks for answers that are NOT slower, to
keep retries out, so it missed this family: the extra calls overload the catalogue and its answers
are 8 to 9 times slower. The flag `--slower-ok` adds a second verdict: calls per request at least
2 times the baseline, the server gets at least 2 times the calls, and the answers are slower.
Without the flag the tool behaves as before.
