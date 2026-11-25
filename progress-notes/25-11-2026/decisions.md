
## RCA Studio: demo data restored, simpler tree, data sources

- **The WSL data folder was deleted on 18-11** (disk cleanup in another session), so the
  partner traces, links and runs were gone from the UI. Restored from: the original archives
  (extracted, not read), the link map found in the 04-11 session log, and the final-pass
  verdicts in the local, git-ignored results folder. The copy on Trillium is the first pass
  only (before the blueprint fixes), so it must not be used for demos.
- **Tree**: runs are listed only under their trace; a run row starts with its blueprint.
  Why: every run was shown twice and rows under one trace looked the same.
- **Run panel** opens as a tab in the active editor group, not a new column per run.
- **Data sources** (logs, metrics, distributed traces) can be connected to a trace. One
  record shape (time, source, text, fields) and a registry of types, so a new backend is one
  class and the extension does not change (it builds its form from the server's field list).
  Why this shape: we do not know the partner's log / metric systems yet. Built-in types only
  read our dataset's files. Not done: the agent does not use these sources yet; they are for
  viewing. Queries read files from the start (logs 2-4 s, 768 MB of spans up to 10 s).

## v3 collection, group 1 (25-11, from 16:10 UTC) - written by the collection session

VM restarted (new address each start; warm-up 150 s before the first measurement). The
Trillium login had expired, so finished families stay on the VM disk until the next login.

### B3 kill-and-restart loop: calibrated, NOT collected (looks like a duplicate of v2)

Recipe `faults/oom_restart_loop.sh` (carts, `docker update -m`). Measured under 150 users:
- 64 MB: 11 restarts and 24 kills in 120 s; carts never serves. The front-end's rate falls to
  about 0, because users hang on connects to a container that has no address while it restarts.
- 160 MB: ALSO a restart loop: 9 restarts and 20 kills in 120 s, each life 15-20 s, carts
  serves nothing. The front-end keeps answering, with 50-98 errors/s.

160 MB is the limit v2 used for `svc_mem_cap` aggressive on carts. So v2 very likely already
holds this fault. Rule 1 of the candidate list: two recipes that leave the same trace are one
problem. **Not checked on the v2 runs themselves** (Trillium not reachable); to confirm there:
count the JVM starts in the fault window of the `svc_mem_cap` aggressive runs. If they show a
loop, B3 is removed; if they show one kill and a slow phase, B3 is collected at 64 MB.

A side finding for the recipe if it is used: after the limit is restored the service stays down
until Docker's back-off timer fires (up to 60 s here); `docker start` does not shorten it.

### C2 inode exhaustion: NOT collected (nothing creates files)

Counted `openat` calls with O_CREAT and `mkdirat` calls on the whole host for 20 s under the
150-user load with bpftrace: none, from any program. A volume with no free inodes then changes
nothing for a service that only writes to files it already has open. Same kind of result as
`io_cap`. One check only, 20 s; `creat` and `openat2` were not counted.

### B3 settled: it is a duplicate of v2 `svc_mem_cap` (checked on the v2 logs, 18:00 UTC)

Carts log of the 8 v2 Sock Shop `svc_mem_cap` runs: the 3 subtle runs (300 MB) have 8-9 JVM
start banners each; the 5 aggressive runs (160 MB) have 1 (the JVM is killed before it prints
one, and one prints after the limit is lifted). With the calibration (9 restarts in 2 minutes
at 160 MB) this says `svc_mem_cap` is a restart loop at both settings. B3 removed from the
candidate list. Consequence for blueprint 4: its text should say "killed and restarted in a
loop", not "killed once" - to check against its README.

### `net_bandwidth` (D4): collected, on Trillium (17:50 UTC)

- Calibration on the catalogue (it sends a little over 4 Mbit/s): cap 4 Mbit/s p95 4.8 -> 415 ms;
  2 Mbit/s p50 240 ms, p95 2.0 s, rate 260 -> 140/s; 1 Mbit/s p50 1.2 s. No errors anywhere,
  recovery within 20 s. Aggressive = 2 Mbit/s, subtle = 4 Mbit/s.
- 5 of 5 runs accepted: verification confirmed (catalogue p95 4.8 ms -> 1.83-1.88 s), no kernel
  events lost, 2,544-2,645 catalogue server spans over 1 s in the fault and 0 in the baseline,
  0 errors, the rate limit gone after every run.
- On Trillium: `v3/sockshop/net_bandwidth.tar.gz` (14.97 GB), 0 checksum errors. Run 1 has
  1,373 files against 1,385 (12 periodic snapshot files fewer; not looked into). Deleted on the VM.
- The local monitor was stopped by Claude Code for low laptop memory during run 4. The driver
  on the VM finished runs 4 and 5 alone; I checked both by hand afterwards.
