# Running the blueprints on the partner traces (Trillium)

Everything below runs on the Trillium login node. Paths are under
`/scratch/yuvraj17/stratatrace/` (`repo/` is this git repo; the partner traces stay in their
NDA folder and are never copied).

## 1. Host the LLM (only when `squeue -u yuvraj17` shows no `vllm-serve` job)

```bash
cd /scratch/yuvraj17/c7-llm && sbatch -p compute -t 24:00:00 --gpus-per-node=1 --cpus-per-task=24 \
  --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3" \
  serve-llm.sbatch
```
Wait for `logs/vllm-<jobid>.log` to say the server is up, then check `repo/.env` points
`OPENAI_BASE_URL` at that node (`http://trigNNNN:8000/v1`, `RCA_PROVIDER=openai`,
`RCA_MODEL=qwen3.8-27b`). Details and health checks: `Blueprint/LLM-HANDOVER.md`.

## 2. Get the latest blueprints onto the cluster

`cd /scratch/yuvraj17/stratatrace/repo && git pull` after the push. Blueprints 0, 8, 9, 10, 11
and the patched tools of 1-7 must be present under `repo/Blueprint/latency/`.

## 3. Run the agent on every trace x every blueprint

```bash
cd /scratch/yuvraj17/stratatrace && nohup bash run_all_parallel.sh > BATCH_v3.log 2>&1 &
```
`run_all_parallel.sh` holds the five trace paths and the blueprint list
(`BLUEPRINTS=(... 7_packet_drop 8_cpu_starvation 9_syscall_stall 10_irq_imbalance
11_priority_inversion)`; add `0_host_triage` to that list for the one-shot screen). It is
resumable: cells with a `verdict.json` are skipped. One trace at a time per blueprint, five
traces in parallel. Outputs: `ciena_out/<trace>/<blueprint>/{run.log,transcript.json,verdict.json}`,
then `summarize.py` writes `ciena_out/SUMMARY.md` and `results.csv`.

One cell by hand:
```bash
bash run_trace.sh "<trace dir>" Blueprint/latency/0_host_triage "<out dir>"
```

## 4. The tools alone, without the LLM (what the calibration used)

```bash
bash validate_sched.sh          # five traces: slice once, run every scheduling tool
bash validate_pi.sh cut; bash validate_pi.sh run   # our own priority_inversion / lock_contention runs
```
Outputs under `sched_validate/<run_id>/`: `slice.txt`, `pidmap.tsv`, one `.txt` per tool, and
`irq_balance_vs_baseline.txt` for the with/without-load pair. Read the `VERDICT:` lines first.

## 5. What a good result looks like (03-11-2026 calibration)

| trace | expected verdict | from |
|---|---|---|
| partner case 1, card A and B | `runq_wait`: STARVED BY CROWD (66-84 same-prio threads on the comms thread's core, max waits 30 ms, other cores idle) | 8_cpu_starvation |
| partner case 1, card C (priority already raised) | `runq_wait`: NOT STARVED; `syscall_stall`: STALL in `clone` 0x100011, 57-70 ms, 2 times, froze 3+ threads in D for ~48 ms | 9_syscall_stall |
| partner case 3, with load | `irq_balance`: RX CONCENTRATED ON CPU 0, ksoftirqd/0 42% | 10_irq_imbalance |
| partner case 3, without load | every screen negative (SPREAD EVENLY, NO WORK-CLASS SYSCALL, NO LOCK PROBLEM) | normal |

Anything the agent says beyond those lines must be backed by a tool output it quotes.
