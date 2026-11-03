# Hosting the LLM on Nibi (SHARCNET) — handover

Written 2026-11-03. Counterpart of `LLM-HANDOVER.md` (Trillium). Owner: yuvraj17.
Why Nibi: Trillium's GPU queue was too busy; Nibi has 348 nodes of 8x H100 80 GB.

## What Nibi has (checked 2026-11-03)

| Resource | Detail |
|---|---|
| H100 nodes | **348 x 8 H100 SXM 80 GB** (640 GB GPU memory per node), 112 Sapphire Rapids cores, 2 TB RAM; plus 96 MIG-split H100 nodes, 62 MI300A, 2x A100, A5000/T4 |
| Scheduling | per GPU: `gpubase_bygpu_b1..b5` = 3 h / 12 h / 1 d / 3 d / 7 d; whole node: `gpubase_bynode_b1..b5`; `gpubackfill` (1 d); `gpubase_interac` (8 h). Name two partitions (`-p gpubase_bygpu_b2,gpubackfill`) and whichever has room first takes the job |
| Account | `def-naser2_gpu` (qos `normal`); `--mem` is allowed (and used) |
| Queue (03-11) | ~4,300 pending GPU jobs; 336/348 H100 nodes partly used, 0 idle: 1- and 4-GPU jobs fit into partial nodes, an 8-GPU whole node waits behind ~116 node jobs |
| Storage | `/scratch/yuvraj17` 1 TiB quota (wiped 03-11 on the user's say-so; now holds `c7-llm/`); `/project/def-naser2` 931 GiB shared; `/home` 50 GiB |
| Software | `python/3.12.4`, `cuda/12.6`/`12.9` modules; the Alliance pip wheelhouse hijacks `pip install vllm` here too -> `uv` (in `~/.local/bin`) with a standalone CPython 3.12.16 (`~/.local/share/uv`) |
| Internet | login node yes (`huggingface.co` reachable); compute nodes assumed no -> `HF_HUB_OFFLINE=1`, everything staged on /scratch |
| Access | one hop: `ssh nibi` (WSL control socket, Duo MFA done by the human) -> login `l4.nibi.sharcnet` |

## Model plan

| Option | Model | GPUs | Why / why not |
|---|---|---|---|
| 1 (first) | **Qwen3.8-27B** BF16, 52 GB | 1 H100 | the Trillium-verified setup (`qwen3_xml` tool parser, `qwen3` reasoning parser, 131k context, prefix caching); fastest queue |
| 2 | GLM-5.3-Flash **NVFP4** (RedHatAI), 169 GB | 4 H100, TP=4 | near-frontier 320B/A18B MoE; fits a partly used node; NVFP4 on Hopper runs through vLLM's slower Marlin path |
| 3 (best) | **GLM-5.3-Flash official FP8** (zai-org), ~330 GB | 8 H100, TP=8 (whole node) | native FP8 on Hopper = fast path and full release precision; did NOT fit Trillium's 320 GB nodes; waits for a whole node |

Parsers (verified on Trillium's vLLM 0.32.0): Qwen3.8 -> `--tool-call-parser qwen3_xml --reasoning-parser qwen3`
(`hermes` returns `tool_calls: null` silently); GLM-5.3 -> `--tool-call-parser glm47 --reasoning-parser glm47`.

## Files (`/scratch/yuvraj17/c7-llm/` on Nibi; sources in `~/nibi-llm/`)

| file | what |
|---|---|
| `setup_nibi.sh` | one-time staging, idempotent (markers in `.done/`): uv venv + `vllm==0.32.0` + `vllm download-kernels` + `hf download` of the models; log `logs/setup.log` |
| `serve-llm.sbatch` | the server job (ported from Trillium; account/partition/mem/paths changed; smoke-tests a completion AND a native tool call into `logs/smoke-*.json`) |
| `submit-qwen.sh` | 1 GPU, 12 h, `gpubase_bygpu_b2,gpubackfill` |
| `submit-glm.sh [nvfp4\|fp8]` | 4 GPUs (12 h) or a whole node (`gpubase_bynode_b2,gpubackfill`) |
| `tunnel.sh` | laptop `localhost:8000` -> the Nibi server (one hop) |
| `bridge.sh start\|stop\|status` | Nibi server -> laptop -> **Trillium login node** `localhost:8000`, so the agent on Trillium (where the partner traces are) can use the Nibi model: set `OPENAI_BASE_URL=http://localhost:8000/v1` in `repo/.env` there |

## Runbook

```bash
# staging (login node, already launched 03-11; re-run is a no-op for finished steps)
nohup bash /scratch/yuvraj17/c7-llm/setup_nibi.sh > /dev/null 2>&1 &
tail -5 /scratch/yuvraj17/c7-llm/logs/setup.log; ls /scratch/yuvraj17/c7-llm/.done

# serve
bash /scratch/yuvraj17/c7-llm/submit-qwen.sh          # or: bash submit-glm.sh nvfp4 | fp8
squeue -u yuvraj17; grep -h "^node:\|server up\|endpoint" /scratch/yuvraj17/c7-llm/logs/serve-<jobid>.out
cat /scratch/yuvraj17/c7-llm/logs/smoke-tool-<jobid>.json   # must contain "tool_calls"

# reach it from Trillium (from WSL on the laptop)
bash bridge.sh start      # prints what trillium sees on localhost:8000
```

## Quirks found on Nibi (each cost one failed step on 03-11)

1. The pip wheelhouse hijack (dummy opencv wheel) applies on Nibi exactly as on Trillium: use `uv`.
   `uv pip install vllm==0.32.0` took 41 min on the login node (slow Lustre, 17 GB of wheels).
2. `/home` is mounted on compute nodes (unlike Trillium's GPU nodes), so the uv-managed Python can live in `~/.local/share/uv`; caches still go to /scratch (`serve-llm.sbatch` sets every cache dir).
3. Per-GPU partitions share nodes: ask for `--cpus-per-task` and `--mem` in proportion (14 cores and ~250 GB per GPU on an 8-GPU node); `--mem` is required here (Trillium forbade it).
4. **GPU requests need the type:** `--gpus-per-node=h100:1`, not `=1` ("There is no 1 GPU-type on the system").
5. **Never pass `-p`:** Nibi rejects an explicit partition ("submit without --partition, the scheduler redirects") and routes by walltime + resources itself (12 h -> `gpubase_bygpu_b2,gpubackfill`).
6. **`vllm download-kernels` cannot run on the login node** (no GPU -> "Failed to infer device type"). The kernels are installed by hand with the commands FlashInfer's own CLI prints (`python -m flashinfer install-cubin-wheel --dry-run`): `flashinfer-cubin==0.7.0.post1` from `https://flashinfer.ai/whl`, and `flashinfer-jit-cache==0.7.0.post1+cu130` + `flashinfer-jit-cache-sm90a==0.7.0.post1+cu130` from `https://flashinfer.ai/whl/cu130/` (`install_kernels.sh`). PyPI's `flashinfer-cubin` stops at 0.6.13, which is why a plain install fails.
7. Downloads are fast (Qwen's 55.6 GB in 2 min with `hf_transfer`); the login nodes are the slow part (loads 20-45 from other users' runaway processes - the web portal hangs for the same reason).
