# Blueprint 44 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `zero_window.py` on `slow_reader` |
|---|---|
| r1-r5 | 172.18.0.1 advertised a window of zero 800 times in 20 s on 200 connections to the catalogue (172.18.0.10:80), 0 in the baseline; the catalogue's next data left while `python3` was running |

Quiet on the other 45 runs; reversed quiet in all 50. No zero-window segment at all in the 95 other
slices. Bars (50 segments on 10 connections, baseline at most 10%) set before the first run and not changed.
The nearest family is `slow_client` (blueprint 31): slow on the sending side, with no zero window.

Changed after run 1, and why:
- The first version read a field called `window`; the trace calls it `window_size`. The self-test
  used the wrong name too, so it passed and the tool saw nothing. Only the name changed.
- The first version named the reader's program from every packet of its address and printed
  `traefik`, then `docker-proxy`. Both were wrong: several programs send from that address, and an
  ACK is sent from whatever context the kernel is in. The reader is now named by address and interface.
