# Blueprint 48 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 60 s of the process events from 62 s before the injection and from 2 s after it.

| run | `unreaped.py` on `code_zombie_procs` (the catalogue, `app`) |
|---|---|
| r1 | 235 children started; 227 ended and 227 of those never freed (100%), 0 in the baseline |
| r2 | 239 started; 232 of 232 never freed |
| r3 | 235 started; 227 of 227 never freed |
| r4 | 232 started; 223 of 223 never freed |
| r5 | 227 started; 220 of 220 never freed |

Quiet on the other 45 runs; reversed quiet in all 50. No other parent had an unreaped child; the
busiest parent (the collection's script) started 1,034 children and all were freed. Bars (20
unreaped, 80% of the ended children, baseline at most 10%; a child that ended in the last 2 s
is not counted) set before the first run and not changed.
