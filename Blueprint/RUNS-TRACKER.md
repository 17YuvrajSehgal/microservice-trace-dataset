# Runs & evaluation tracker

Living record of **what blueprints exist, what runs we have, where they live, and what has been
evaluated**. Update the `eval` column as `Blueprint/eval` produces scored results.

Legend: ✓ present/done · ⬜ not done · — not applicable (that fault type does not exist in that
dataset). "indexed" = `<run_id>.tsv.gz` built and co-located (what the agent reads).

---

## 1. Blueprints (`Blueprint/latency/`)

| # | blueprint | folder | tools | applies to |
|---|---|---|---|---|
| 1 | svc_cpu_cap | `1_svc_cpu_cap` | 10 | agentic, Sock Shop, Train Ticket |
| 2 | noisy_neighbor | `2_noisy_neighbor` | 10 | Sock Shop, Train Ticket |
| 3 | slow_db | `3_slow_db` | 13 | Sock Shop, Train Ticket |
| 4 | svc_mem_cap | `4_svc_mem_cap` | 11 | agentic, Sock Shop, Train Ticket |
| 5 | svc_net | `5_svc_net` | 11 | Sock Shop, Train Ticket |

Agentic only has CPU-cap and memory-cap faults, so only blueprints 1 and 4 apply there.

---

## 2. Runs inventory & evaluation status

One row per (blueprint × dataset). `runs` counts the runs whose fault matches the blueprint
(fault + control). `traces` is where the raw kernel trace lives; `indexed` is how many have a
built index locally right now.

| blueprint | dataset | runs | fault | control | traces | indexed | eval |
|---|---|---|---|---|---|---|---|
| **svc_cpu_cap** | agentic — Claude | 42 | 31 | 11 | **local** `agentic-runs/1_svc_cpu_cap/.../runs` | ✓ 42/42 | ✓ 14/31 faults, 11/11 controls (cap25 8/10, cap50 6/10, cap100 0/11) |
| | agentic — Codex | 40 | — | — | Zenodo (meta-only local) | ⬜ 0/40 | ⬜ |
| | Sock Shop | 8 | 8 | +10 normal | Trillium | ⬜ 0/8 | ⬜ |
| | Train Ticket | 8 | 8 | +10 normal | Trillium | ⬜ 0/8 | ⬜ |
| **svc_mem_cap** | agentic — Claude | 44 | 44 | 0 | **local** `agentic-runs/3_memory_cap/runs` | ✓ 44/44 | ⬜ |
| | agentic — Codex | 44 | — | — | Zenodo (meta-only local) | ⬜ 0/44 | ⬜ |
| | Sock Shop | 8 | 8 | +10 normal | Trillium | ⬜ 0/8 | ⬜ |
| | Train Ticket | 8 | 8 | +10 normal | Trillium | ⬜ 0/8 | ⬜ |
| **noisy_neighbor** | Sock Shop | 8 | 8 | +10 normal | Trillium | ⬜ 0/8 | ⬜ |
| | Train Ticket | 8 | 8 | +10 normal | Trillium | ⬜ 0/8 | ⬜ |
| **slow_db** | Sock Shop | 11 | 11 | +10 normal | Trillium | ⬜ 0/11 | ⬜ |
| | Train Ticket | 11 | 11 | +10 normal | Trillium | ⬜ 0/11 | ⬜ |
| **svc_net** | Sock Shop | 5 | 5 | +10 normal | Trillium | ⬜ 0/5 | ⬜ |
| | Train Ticket | 5 | 5 | +10 normal | Trillium | ⬜ 0/5 | ⬜ |

**"+10 normal"** = each microservice app has 10 fault-free runs shared as controls across all
blueprints (not per-blueprint copies).

### Totals for the 5 blueprints

| | runs matching a blueprint | locally traced | evaluated |
|---|---|---|---|
| agentic (Claude, local CTF) | 86 | **86** (indexed ✓) | 0 |
| agentic (Codex, Zenodo) | 84 | 0 | 0 |
| Sock Shop (Trillium) | 40 fault + 10 normal | 1 (svc_cpu_cap sample) | 0 |
| Train Ticket (Trillium) | 40 fault + 10 normal | 0 | 0 |

---

## 3. Where the runs live

| dataset | location | notes |
|---|---|---|
| agentic — Claude | `agentic-runs/` (this repo) | 132 runs carry a raw CTF (`trace/kernel/`); of these 86 are CPU/memory caps. **All 132 indexed 2026-10-22** into `Blueprint/eval/index-agentic/` (56 MB, gitignored) via `build_indexes.py`. |
| agentic — Codex | Zenodo DOI `10.5281/zenodo.23523441` | Only `meta/` ships in `agentic-runs/`; kernel traces are the 2.6 GB Zenodo archive. See `os-noise-for-agentic-ai/DATA.md`. |
| agentic — e2e / threads / io | `agentic-runs/2_*`, `4_*`, `*_e2e_*` | No matching blueprint (threads = run-queue, io = disk cap, e2e = no trace). 132-86 = 46 local CTFs are these. |
| Sock Shop | Trillium `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/sockshop/<fam>/<run>/` | 170 runs total; 40 across the 5 blueprint families + 10 normal. **Verified 2026-10-22.** Each run has `kernel/kernel/`, `ground_truth.json`, `meta/` — fully ready to index + eval on Trillium. (Each run also has a sibling `<run>_metrics/` dir — ignore it when counting.) |
| Train Ticket | Trillium `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/trainticket/` | 134 runs total; 40 across the 5 blueprint families + 10 normal. Same layout, verified. |
| microservice indexes | Trillium `/scratch/yuvraj17/stratatrace/dataset/index-v2/` | **Partial** — 66 `tsv.gz` (~3 per family, svc_mem_cap and normal = 0). The old q2 subset. A **full index build is needed** before a complete eval (`build_ctf_index.py` with `tools/bt21.sh`). |
| local microservice | `data-sample/svc_cpu_cap/svc_cpu_cap_aggressive_steady_r1` | one Sock Shop svc_cpu_cap run, index in `demo/data/`. The only microservice run traced locally. |

---

## 4. How to run an evaluation (matched arm)

```bash
cd Blueprint/eval
# build indexes for a runs-root that has local CTFs (agentic)
BT2=babeltrace2 python3 build_indexes.py <runs_root> <index_root>      # under WSL
# then score the correct blueprint over its matching runs
python eval_matrix.py --problem svc_mem_cap --runs-root <runs_root> \
    --index-root <index_root> --out results/<dataset>/svc_mem_cap --jobs 4
```

Each cell writes `result.json`; `eval_matrix` prints `detected N/total`. Commit the scoreboards
under `Blueprint/eval/results/` so a collection survives sessions, and tick this table's `eval`
column (e.g. `✓ 25/44`).

---

*Last updated: 2026-10-22. Counts verified from `agentic-runs/` (local CTF + ground truth) and
`blueprints/docs/DATASET-v2-INVENTORY.md` (microservice v2).*
