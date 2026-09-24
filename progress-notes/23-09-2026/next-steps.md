# Next steps, as of end of 23-09-2026

## Done today
- Agent v2 (LangGraph, planner/workers, scratchpad, sandboxed `run_python`)
- Four silent bugs in the tool layer, found by cross-checking tools against each other
- `svc_net` blueprint + `pid_ns` answer format: Sock Shop given arm 0/30 -> 10/30 at n=30
- `svc_cpu_cap` blueprint: Sock Shop given arm 0/30 -> 6/30 at n=30
- `nsmap.py`, so the scorer checks a container answer instead of crediting any namespace

## Before the 720-run campaign
1. **Decide what to do about Train Ticket `svc_cpu_cap`.** The injection does not engage
   (0.2 cap against 0.004 CPU used). Options: re-collect it calibrated, drop it from the
   per-service comparison, or report it as a measured non-event. It cannot stay as-is.
2. **Separate `abstained` from `miss` in the headline window metric.** The agent is now
   penalised for correctly reporting a non-event.
3. **`slow_db` is 24/60 and 3/60** and has the same shape - a container that runs throughout.
   Worth the same treatment before the campaign, so the headline is "per-service localisation"
   rather than two of three.

## Campaign parameters, measured
- Agent cells must run on the **login node**: compute nodes resolve the API endpoint but
  TCP 443 is blocked.
- `--jobs 6` works on both applications. 12 was killed by the watchdog, 4 is safe but slow.
- ~215 s a cell, ~345k tokens a cell. 720 cells is roughly 7 hours at jobs 6.

## Open
- Train Ticket container identity resolves only partially, so per-service WHERE there is
  partly unverifiable. The `container_unverified` outcome records this rather than hiding it.
- Train Ticket `svc_net`: the ranking finds a container downstream of the injected one.
  Hypothesis is that a delayed service starves its dependencies harder than itself; the test
  is whether the impaired one drops on both send and receive while a victim drops on receive.
