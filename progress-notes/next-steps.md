# Next steps

_Updated 3 November 2026, end of session. The 17 September list (Train Ticket VM, svc_net
re-collection) is archived in `17-09-2026/next-steps.md`._

## Where things stand

The scheduling-family blueprints for bare-metal hosts exist and are calibrated
(`Blueprint/latency/0_host_triage`, `8_cpu_starvation`, `9_syscall_stall`, `10_irq_imbalance`,
`11_priority_inversion`; see `03-11-2026/decisions.md`). Tool-only runs on the five partner
line-card traces reproduce all three engineers' root causes with their numbers, call the healthy
baseline clean, and reject the suspected starvation on the card where the priority had already
been raised. The whole `Blueprint/latency` tree is deployed on Trillium
(`/scratch/yuvraj17/stratatrace/repo/Blueprint/latency`, checksums verified) and
`run_all_parallel.sh` / `summarize.py` there already list blueprints 0 and 8-11.

## Tomorrow, in order

### 1. Re-host the LLM and run the agent matrix on the partner traces
No `vllm-serve` job is running. The sbatch line and the run commands are in
`Blueprint/latency/CLUSTER-RUN.md`. Expect 5 traces x 11 blueprints; the cells that matter are
`0_host_triage` (does the agent route and name the threads by itself?) and 8 / 9 / 10 on their
own cases. Compare the agent's `culprit_thread` / `victim_thread` against
`Blueprint/ciena_out/COMPARISON-SUMMARY.md` (local, NDA). The tool verdicts are the ceiling;
anything the agent adds must quote a tool line.

### 2. Blueprint 11 — run it through the agent too
`futex_wait.py` is validated tool-side (`03-11-2026/decisions.md` §8): the labelled
lock_contention and priority_inversion runs both read correctly, the five partner traces are
true negatives. The next check is the agent on `priority_inversion_aggressive_steady_r1` with
`11_priority_inversion` (eval_one.py, Sock Shop index on Trillium) - it must quote the futex
verdict and name waiter / holder / middle threads.

### 3. Push
The 03-11 commits are local only (`git log origin/master..master`). Ask before pushing; the
user has not answered the earlier push question.

### 4. Loose ends
- `6_conn_pool_exhaustion/` is an empty folder with a stale `__pycache__`; delete or build.
- `sched_budget.py` names a process by its last-seen thread comm (pre-existing); on bare-metal
  traces prefer `thread_top.py`.
- The selector experiment (`Blueprint/select_c`) still routes only the microservice families;
  `0_host_triage` is the bare-metal counterpart and was not scored on Sock Shop.
- Train Ticket `svc_mem_cap` re-collection and the N-seed freeze run (31-10 open items) are
  untouched.
