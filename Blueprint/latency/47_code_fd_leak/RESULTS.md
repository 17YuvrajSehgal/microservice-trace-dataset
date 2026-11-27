# Blueprint 47 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of the open and close system calls from 30 s before the injection and from 40 s after it.

| run | `fd_growth.py` on `code_fd_leak` (the catalogue, `app`) |
|---|---|
| r1 | 110 files opened, 36 closed, 74 stayed open (3.7 per second), 0 in the baseline |
| r2 | 110 opened, 35 closed, 75 stayed open (3.8 per second) |
| r3 | 114 opened, 36 closed, 78 stayed open (3.9 per second) |
| r4 | 121 opened, 36 closed, 85 stayed open (4.2 per second) |
| r5 | 117 opened, 35 closed, 82 stayed open (4.1 per second) |

Quiet on the other 45 runs; reversed quiet in all 50.

Changed after run 1 (the first version missed its own family, then fired on two others):
1. It asked that the growth be 20% of ALL the process's opens. The catalogue opens about 150
   sockets per second in normal work, so a clear leak (72 against 1) was 2% of its opens.
2. It counted `dup2`, which reuses a descriptor number and adds nothing. Two Java services showed a
   growth of 60 that was all `dup2`.
3. It counted sockets and files together. In `code_chatty_calls` the catalogue then showed a growth
   (344 sockets) and in `dns_delay_jvm` a proxy did (44): connections piling up, not a leak. The
   verdict is now for files only.
4. The share bar came back, for files only: cadvisor opened 8,006 files in one slice and had 68
   open at the end (under 1%); the leaking service kept 74 of 110.
The bars now: 30 files that stay open, 20% of the files opened, baseline at most 20% of it.
