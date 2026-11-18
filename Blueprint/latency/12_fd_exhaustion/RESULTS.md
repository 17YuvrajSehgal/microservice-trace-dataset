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

## All Sock Shop runs (17-11-2026)

Every Sock Shop v2 run (170), SLURM job 2882127 on Trillium (one node, 27 min, shared by
blueprints 12, 13 and 14). The tool is unchanged. Same slices as the Train Ticket check.
Outputs: `work/dx_check/sweep_ss/`.

| runs | fault slice | baseline slice |
|---|---|---|
| `fd_exhaustion`, 5 | FD EXHAUSTION: `node` (the front-end), 4-168 EMFILE in 90 s, highest fd 72-90, 6-8 restarts | NO FD PRESSURE |
| `anomaly_net` burst, 3 | FD EXHAUSTION: `traefik` (the edge router), 3,598-7,304 EMFILE on `accept4`/`socket`, highest fd 1023, 0 restarts | NO FD PRESSURE |
| `code_event_loop_block`, 5 | FD EXHAUSTION: `traefik`, 1,258-10,035 EMFILE, highest fd 1023, 0 restarts | NO FD PRESSURE |
| `dns_delay` r2, r4, r5 | FD EXHAUSTION: `traefik`, 9,271-43,036 EMFILE, highest fd 1023, 0 restarts | NO FD PRESSURE |
| all other runs, 152 | NO FD PRESSURE | NO FD PRESSURE |
| 2 runs | no result: the slice cut failed | |

5 of 5. In 11 runs of three other families the tool gives the same verdict for the edge router.

Those 11 verdicts are true and they are not the root cause. In each of those faults the
front-end answers slowly, so connections pile up in the edge router until it reaches its own
limit of 1,024 descriptors (highest fd 1023). It is a second-order effect of another fault.
The two cases differ in what the verdict line already prints:

| | the injected fault | the cascade |
|---|---|---|
| process | the service whose limit was lowered | the proxy in front of a slow service |
| highest fd | 72-90 (a lowered limit) | 1023 (the default limit) |
| restarts | 6-8 | 0 |
| EMFILE count | 4-168 | 1,258-43,036 |

The tool was NOT changed: a rule on these numbers would be fitted to one application. On
Train Ticket the injected fault itself has 0 restarts and a highest fd of 1308-1528, so
neither number is a general test. The README now tells the reader to ask why connections
piled up before reporting.

With Train Ticket: 10 of 10; 0 false alarms in 129 Train Ticket runs, 11 cascade verdicts in
163 Sock Shop runs.
