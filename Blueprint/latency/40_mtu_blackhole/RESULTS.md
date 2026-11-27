# Blueprint 40 results (tool only, 27-11-2026)

Tested on the Trillium login node, 26/27-11-2026, on the 20 group-4 runs (`rt_hog`, `mtu_blackhole`, `login_bruteforce`, `unexpected_exec`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g4/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). The suspect slice here starts AT the injection (0-10 s); a slice at 40 s finds nothing.

| run | `big_resends.py` on `mtu_blackhole` |
|---|---|
| r1 | 149 segments resent, 172.18.0.7 (database proxy) -> 172.18.0.11 (catalogue), all of 596+ bytes; 0% of the smaller ones |
| r2 | 146, 625+ bytes |
| r3 | 149, 596+ bytes |
| r4 | 148, 596+ bytes |
| r5 | 148, 596+ bytes |

Quiet on the other 15 group-4 runs, where the busiest path resends 176-356 segments of every size
(down to 5 bytes) and resent as much in the baseline. Reversed quiet in all 20.

Rule history (all after seeing these runs): a fixed 1,000-byte cut-off found 0 of 5 (the dropped
segments were 537-999 bytes); "at least 80%, then 50%, of the segments above the cut-off resent"
found 0 and then 3 of 5 (the share swung 37-78%: a dropped segment's resends back off, so a 10 s
slice often holds only its first send); the final rule is the size split (every resent segment
200+ bytes, at most 5% of 50+ smaller segments resent).
