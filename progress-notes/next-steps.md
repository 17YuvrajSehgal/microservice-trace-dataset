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

The agent matrix on the five partner traces ran twice on 03-11 (`03-11-2026/decisions.md`
§10-11). After the rule and tool fixes every cell of blueprints 0, 8, 9, 10, 11 is either the
engineers' answer, `normal`, or one of two documented real-but-secondary findings (card C / 8,
card B / 9). **Everything now runs on Nibi** (LLM + traces + runner; `NIBI-HANDOVER.md`).
Trillium is not needed for the partner work.

## Next, in order

### 1. Close the loop on the partner traces
- Card A / 8 with the required thread fields (running at session end; result in
  `ciena_out_v3/wlai-*/8_cpu_starvation/verdict.json` on Nibi). If the fields are still empty,
  the schema change (`utils.py`, `622964a`) did not reach the model and needs a look at how
  `_SUBMIT_DEF` is sent.
- Show the engineers the two secondary findings (card C: siblings starved after the nice -20
  raise; card B: the 364 ms journal-freezing write) and ask whether they are known.
- Re-host when needed: `bash /scratch/yuvraj17/c7-llm/submit-qwen.sh` on Nibi (12 h batch) or
  the `srun --qos=interac` line in `NIBI-HANDOVER.md` (8 h, fast lane); update `repo/.env` host.

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
