# Handoff — matched-blueprint eval, what to re-run with the new GPT key

**Read first:** `Blueprint/eval/results/RESULTS.md` (full current results) and
`Blueprint/eval/README.md` (how the harness works). This file is the short "what's left" map.

**Goal of the whole eval:** how often does the agent find the fault **when handed the correct
blueprint** (the "matched arm")? Blueprint *selection* is a separate, later experiment — ignore it
here. Everything runs from the `Blueprint/` tree (agent = `Blueprint/agent`, blueprints =
`Blueprint/latency/*/README_v1.md`, scorer = `Blueprint/eval/score.py`).

---

## 1. The model / key (new GPT key goes here)

Same underlying model as all prior results — the earlier runs went through **OpenRouter**
(`openai/gpt-6-luna`), which routed to OpenAI's gpt-6-luna. The new key is **directly from OpenAI**,
so use the `openai` provider and the bare model id (no `openai/` prefix):

```
RCA_PROVIDER=openai
RCA_MODEL=gpt-6-luna                    # direct OpenAI id (no "openai/" prefix); confirm in your OpenAI dashboard
OPENAI_API_KEY=<the new key>           # a direct OpenAI key, NOT an OpenRouter key
# OPENAI_BASE_URL must be UNSET so calls hit api.openai.com (the SDK default)
```

- Put the key in `.env` (git-ignored) — **never print it**.
- ⚠️ **Delete the `OPENAI_BASE_URL` line.** The current `.env` sets it to the local LM Studio URL
  (`http://localhost:1235/v1`) for the separate Ciena task. Provider `openai` reuses that same var,
  so if you leave it in, every "OpenAI" call goes to localhost, not OpenAI. A cloud backup is
  `.env.cloud.bak`.
- Temperature is **not sent** (default; results so far are "temperature omitted"). Leave it.
- Pricing is GPT-6 Luna: $0.10 / 1M in, $0.50 / 1M out (confirm current OpenAI rates).
  `--budget-usd N` stops before a cap.
- ⚠️ **`rerun_sockshop.sh` still hard-codes the OpenRouter vars** (`RCA_PROVIDER=openrouter`,
  `OPEN_ROUTER_API_KEY`). Override them with the `openai` vars above (export before the script, or
  edit the script) or it will try the dead OpenRouter key.

**Lessons from the first direct-OpenAI run (31 Oct) — the TT re-run + N-seed runs will hit these:**
- **Strip CRLF from the key.** A key transferred out of the Windows `.env` keeps its trailing `\r`;
  the SDK then sends `Bearer …\r` and fails with `APIConnectionError` (really `LocalProtocolError:
  Illegal header value`). `sed -i 's/\r$//'` the key file. A clean way to run without the key ever
  touching the command line: put it in `~/openai_key.env` (chmod 600) and `set -a; . ~/openai_key.env;
  set +a` in the run script (see `~/run_mem_eval.sh` on Trillium).
- **`reasoning_effort=none` is required** for gpt-5.x luna via chat.completions (OpenAI exposes its
  reasoning only through the Responses API). `config.py` now pins it for `PROVIDER=openai`
  (env-tunable `RCA_REASONING_EFFORT`); without it every call 400s. This means these runs have
  reasoning OFF — consistent with the OpenRouter chat path, but note it beside any cross-provider
  comparison.
- **Model id:** `gpt-6-luna` resolves on direct OpenAI as an alias (the dashboard lists
  `gpt-5.6-luna`); both work, same underlying model as the OpenRouter runs.
- **Connectivity:** the login node CAN reach `api.openai.com` (and openrouter.ai); compute nodes
  cannot. Keep agent runs on the login node.

---

## 2. The 4 datasets — what is runnable

Runnable = has a **kernel CTF trace** + ground truth + a built index. The eval is **kernel-trace
only** (no metrics, logs, or spans).

| dataset | where | kernel trace? | status |
|---|---|---|---|
| **Agentic — Claude Code** | local `agentic-runs/` (132 CTF; indexes in `Blueprint/eval/index-agentic/`) | yes | **DONE** (cpu + mem) |
| **Agentic — Codex CLI** | local `agentic-runs/1_svc_cpu_cap/agentic-os-noise/runs_codex*` (130 cpu runs) | **yes — as decoded text** `trace.txt.gz` (raw-CTF `trace/` dir is empty) | **runnable after building indexes from the text** (§F). Only **svc_cpu_cap** present locally |
| **Microservice — Sock Shop** | Trillium `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop` | yes | **PARTIAL** (v2 single-run preliminary); **svc_mem_cap re-collected 29–30 Oct w/ memcg → now evaluable, agent eval NOT yet run** |
| **Microservice — Train Ticket** | Trillium `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/trainticket` | yes | **only v1 blueprints run; svc_mem_cap still NOT evaluable (no memcg re-collection yet)** |

---

## 3. The 5 blueprints + matched mapping

There are **5 evaluable blueprints** (the `6_conn_pool_exhaustion/` folder is a tools-only stub —
the team decided to **stop at 5**; see `results/NEXT_RESULTS.md` probe findings for why a 6th has
no robust kernel signal in v2).

| problem (ground-truth family) | blueprint (`--problem` value → folder) |
|---|---|
| svc_cpu_cap | `1_svc_cpu_cap` |
| noisy_neighbor | `2_noisy_neighbor` |
| slow_db | `3_slow_db` |
| svc_mem_cap | `4_svc_mem_cap` |
| svc_net | `5_svc_net` |

`datasets.py` maps these automatically; `--problem svc_cpu_cap` picks `1_svc_cpu_cap` on its own.

---

## 4. What is already DONE — do not re-run (unless you want fresh samples)

Both already run on gpt-6-luna (via OpenRouter, same underlying model as direct OpenAI):

| section | runs | result |
|---|---|---|
| svc_cpu_cap × agentic (Claude) | 42 | 14/31 faults, 11/11 controls, $4.48 |
| svc_mem_cap × agentic (Claude) | 44 | 25/44 raw; **44/44 aligned with whether the cap actually fired**, $3.60 |

Same model, so these stand — re-run only if you want extra seeds for consistency with the direct-API runs.

---

## 5. What to RE-RUN / RUN — and on which blueprint (priority order)

### A0. Sock Shop svc_mem_cap — ✅ DONE 31 Oct 2026 (3/8 → 8/8 after a blueprint fix)
Ran blueprint **`4_svc_mem_cap`** on the 8 new memcg runs (direct OpenAI gpt-6-luna, matched arm).
v1 blueprint scored **3/8 DETECTED**; an audit of the misses showed the blueprint (not the agent) was
the problem — it demanded a file-cache re-read storm a JVM heap cap can't produce and read the cap's
collapse as a "teardown". After the fixes the **v2 blueprint scores 8/8 DETECTED** (aggr 5/5, subtle
3/3), leakage-audited. Full writeup: `results/RESULTS.md` §svc_mem_cap +
`results/sockshop/JUDGMENTS-svc_mem_cap.md`. Cost ~$2.1 (3 passes). v1 cells preserved at
`results/sockshop/svc_mem_cap_v1blueprint/`.
> `--runs-root` MUST be `.../sockshop/svc_mem_cap` (the family dir), NOT `.../sockshop` — `discover()`
> uses recursive `os.walk`, so pointing at the app dir pulls in the parked
> `_superseded_no_memcg_20261029/` old runs too. Also: delete any **stale** `result.json` cells first
> (there were 7 from a 27 Oct no-memcg run that the resumable harness would otherwise skip).

### A. Train Ticket on the v2 (fixed) blueprints — the main gap
Only **v1** blueprints were run on TT. Re-run on v2 (fixed) blueprints: `1_svc_cpu_cap`,
`2_noisy_neighbor`, `3_slow_db`, `5_svc_net`. **Skip `4_svc_mem_cap`** (see caveats).
> Expect most TT families to come back "not evaluable / normal" — that is a **TT dataset
> weakness** (caps didn't bite, noisy-neighbor too weak on 16 CPUs, net ambiguous), not an agent
> fault. The one TT family with a clear kernel signature is **aggressive slow_db** (was 4/4). Do
> not cite TT detection rates as agent performance.

### B. Sock Shop N-seed final run — the citable numbers
The current SS result (27/31) is a **single run per cell = preliminary**. gpt-6-luna is
nondeterministic, so borderline cells flip on noise. **Freeze the 5 blueprints, then run several
seeds per cell** and report the aggregate. Blueprints `1,2,3,5` (not mem). There is **no
`--seed`/`--repeat` flag** — get N seeds by running the matrix N times into separate `--out` dirs
(e.g. `.../seed1`, `.../seed2`, …) and aggregating.

### C. Resume the 8 rate-limited SS/TT cells
72/80 microservice cells scored; 8 died on API rate limits. The harness is **resumable** — a run
with an existing `result.json` is skipped — so just re-run the same command.

### D. Microservice controls (false-alarm rate)
Run the **normal/uncapped** microservice runs through each blueprint → how often it cries wolf.
Drop `--no-controls` (or run the control runs explicitly).

### E. Control arm — the "does the blueprint help?" comparison
Re-run the same runs with **`--arm none`** (no blueprint handed over) to measure how much the
blueprint adds vs the agent alone.

### F. Codex agentic (svc_cpu_cap) — present as text, needs indexes built
Codex traces ARE local: `agentic-runs/1_svc_cpu_cap/agentic-os-noise/runs_codex*`, **130 cpu runs**,
each with the full kernel trace as **decoded text** `trace.txt.gz` (~360k event lines; the raw-CTF
`trace/` dir is empty). Only **svc_cpu_cap** is present locally (no codex mem/threads/io here — those
would need fetching from the os-noise dataset / Zenodo if wanted).

`build_ctf_index.py` currently decodes **raw CTF** with babeltrace, so it won't run on codex as-is.
Build the count index **from the text instead** — `trace.txt.gz` is babeltrace's own output format,
so pipe `zcat trace.txt.gz` through the same line parser to emit the `<run_id>.tsv.gz` (small
text-input mode on `build_ctf_index.py`, or a short sibling script). Then run matched:
`--problem svc_cpu_cap` → blueprint `1_svc_cpu_cap`.
> Check the text's timestamp base matches the ground-truth window (the Claude CTF is decoded with
> `--clock-gmt`; `meta/clock_anchors.jsonl` has the anchors if a shift is needed).

---

## 6. How to run

**Microservice (Trillium, LOGIN node only — compute nodes have no internet; agent calls the OpenAI API):**
`Blueprint/eval/rerun_sockshop.sh` is the working SS version, but it hard-codes the old OpenRouter
vars — override them as below (or edit the script). For TT, copy it and change `D=` to
`.../trainticket`. The core command:

```bash
cd /scratch/yuvraj17/stratatrace/repo
export RCA_PROVIDER=openai RCA_MODEL=gpt-6-luna OPENAI_API_KEY=<key>   # unset OPENAI_BASE_URL
export ABL_WORKER_STEPS=20 ABL_THREAD_BUDGET=150000        # microservice needs more turns
export BT2=/scratch/yuvraj17/stratatrace/tools/bt21.sh
export CTF_INDEX_ROOT=/scratch/yuvraj17/stratatrace/dataset/index-v2
python Blueprint/eval/eval_matrix.py --problem <p> \
    --runs-root /scratch/yuvraj17/stratatrace/data/stratatrace-v2/<app> \
    --index-root "$CTF_INDEX_ROOT" --out <out>/<p> --no-controls --jobs 6
```

**Agentic (local, Windows — babeltrace via WSL):**
```bash
export RCA_PROVIDER=openai RCA_MODEL=gpt-6-luna OPENAI_API_KEY=<key>   # unset OPENAI_BASE_URL
export ABL_WORKER_STEPS=12 ABL_THREAD_BUDGET=90000         # one-cgroup case, fewer turns
python Blueprint/eval/eval_matrix.py --problem svc_cpu_cap \
    --runs-root agentic-runs/1_svc_cpu_cap \
    --index-root Blueprint/eval/index-agentic --out results/agentic/svc_cpu_cap --jobs 4
```

Useful flags: `--dry-run` (list cells, cost estimate, run nothing), `--arm none` (control),
`--no-controls`, `--limit N`, `--budget-usd N`, `--blueprint <folder>` (override).

**Grading:** agentic is scored automatically by `score.py`. **Microservice is graded BY HAND**
against ground truth + the injection recipe (`Blueprint/eval/JUDGING.md`) — `score.py`'s
keyword/target-string matching mis-scores microservice both ways. Use `gather.py <results_dir>` to
dump truth-vs-verdict per run for the human/LLM judge.

---

## 7. Hard caveats (must know before running or citing)

- **svc_mem_cap on microservice: Sock Shop YES (new), Train Ticket NO.** SS `svc_mem_cap` +
  `anomaly_mem` were re-collected 29–30 Oct 2026 **with memcg tracepoints**
  (`mm_vmscan_memcg_reclaim_*`) and are now evaluable — use the SS runs in `index-v2`, not the
  parked `_superseded_no_memcg_20261029/` ones. **Train Ticket still has no memory tracepoints**, so
  svc_mem_cap stays not-evaluable on TT until TT gets the same re-collection — **skip blueprint 4 on
  TT**. (Agentic/Claude svc_mem_cap is already done, 44/44.)
- **Train Ticket is a weak testbed** — only aggressive slow_db bit kernel-visibly. Do not cite TT
  detection as agent quality; it is a dataset intensity/collection limitation.
- **Matched arm only** — the correct blueprint is handed over. These numbers say nothing about the
  agent *choosing* the blueprint.
- **On Trillium, check `bt21.sh --version` says 2.1.2.** If its paths go stale it silently falls
  back to babeltrace 2.0.4, which **cannot read our traces** → every run looks empty.
- **Every run needs its index** (`<run_id>.tsv.gz`) under `--index-root`, keyed by the
  ground-truth dir name. Build with `Blueprint/eval/build_ctf_index.py` (one babeltrace decode per
  run; the `.sbatch` batches it on the cluster).
- **Prior numbers before the leak audit + blueprint-worker + CRLF fixes are invalid** and were
  deleted. Only run on the current blueprints.
