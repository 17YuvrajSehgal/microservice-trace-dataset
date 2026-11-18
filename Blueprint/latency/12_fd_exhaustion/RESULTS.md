# Blueprint 12 results

## Train Ticket check (17-11-2026)

Every Train Ticket v2 run (134), SLURM job 2881327 on Trillium (one node, 53 min, shared by
blueprints 11, 12, 13, 14 and 16). The tool is unchanged from the Sock Shop check. Outputs:
`work/dx_check/sweep_tt/`.
Slices: 90 s from 10 s before the injection, and a 30 s baseline from 50 s before it.

| runs | fault slice | baseline slice |
|---|---|---|
| `tt_fd_exhaustion`, 5 | FD EXHAUSTION, 5 of 5: one JVM (pid 19966), 632-640 EMFILE on `openat` and 39-40 on `accept`/`socket` in 90 s, highest fd 1308-1528 | NO FD PRESSURE |
| all other Train Ticket runs, 129 | NO FD PRESSURE | NO FD PRESSURE |

5 of 5, 0 false alarms in 129.

Two differences from Sock Shop, both correct readings:
- The verdict prints **0 restarts**. The Train Ticket service keeps running at its limit; the
  Sock Shop front-end crash-loops. The restart count is not needed for the verdict.
- There are three verdict lines per run. They are three thread names of the same process
  (`sentinel-system`, `http-nio-18888-`, `com.alibaba.nac`), not three culprits: read the pid.
