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

The evening added the selector work (`03-11-2026/decisions.md` §12-13): selector C v7 ran on
29/42 Sock Shop cells (slow_db 7/11, up from v6's 2/11), `select_d` (one router for container
and bare-metal hosts) is 5/5 on the partner traces, blueprint 12 `fd_exhaustion` is built and
4/4 in the matched arm. No model server is running.

## Next, in order

### 1. Host a model and resume the three batches (Trillium, through the bridge)
Host on Nibi (`NIBI-HANDOVER.md`: `submit-qwen.sh` or the interactive `srun --qos=interac`
lane), then from WSL `ssh -O forward -L 8000:<node>:8000 nibi` and
`ssh -O forward -R 8001:localhost:8000 trillium` (Trillium's `.env` points at `localhost:8001`).
Keep total agents at or below ~8 per server (one H100 holds ~9 long contexts; 14 agents sat at
9 running / 32 waiting and cells took 35 min). Then, on Trillium:
- `bash /scratch/yuvraj17/stratatrace/run_select_c7_qwen.sh` - finishes C v7 (3 svc_net + the
  10 normal controls; the controls decide whether v7's `normal` bar holds).
- `SEL_ARM=sockshop_d_qwen SEL_PAR=4 bash Blueprint/select/run_select_d.sh` - the 42 Sock Shop
  cells + the 10 lock-family runs through the unified router (env as in `run_select_c7_qwen.sh`).
- `bash /scratch/yuvraj17/stratatrace/run_fd_test.sh` after deleting `bp_eval/fd12/select_d/.../r3`
  - re-tests r3 through the fixed selector and runs the normal control; then r4/r5.
Score: `Blueprint/select/select_score.py <arm dir> --data-root data/stratatrace-v2/sockshop`.

### 2. Partner traces
- Show the engineers the two secondary findings (card C: siblings starved after the nice -20
  raise; card B: the 364 ms journal-freezing write) and ask whether they are known.
- Selector D results live in `Blueprint/ciena_out/v3/<trace>/select_d/` (local mirror).

### 3. Scorer debt
`nsmap` cannot map a container that restarts (several pid_ns generations): on the fd runs it
assigns the front-end's namespace to `carts-db`, so a correct "node in pid_ns N" scores `where =
wrong` unless the agent also names `front-end`. Fix the map (group generations by image/comm) or
accept the comm+pid_ns form for restart-looping targets.

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
