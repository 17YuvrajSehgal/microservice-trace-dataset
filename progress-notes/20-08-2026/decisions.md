## Dataset reorganized into a publishable, self-contained layout (2026-08-20)

Problem (Yuvraj): the dataset was scattered — kernel_l2.jsonl lived only in the
/scratch working set (derived 2026-08-16, after the /project archives were made),
and metrics + load.csv lived in a SEPARATE `_aux_metrics_load.tar.gz` per app and as
`<run>_metrics/` + `<run>_load.csv` SIBLINGS of the run dir. So no single download
gave a reader a complete run.

Decision: build a new release tree `/scratch/yuvraj17/stratatrace-v1/` where **every
run folder is self-contained**, and **never touch the originals** (/project archives
are read-only inputs; nothing deleted). Built in /scratch, not /project, because
/project has only ~700 GB free and the new archives are ~330 GB — the originals stay
put until Yuvraj decides to retire them.

Layout: per-fault-family tar.gz per app (download one anomaly at a time, as asked)
+ common files hoisted to the top (README, UNDERSTANDING-DATASET, DATASET_GUIDE,
manifest.csv, fault_catalog, provenance/, tools/stratatrace with the derivers) +
a **stratatrace-lite.tar.gz** (~1 GB) holding every run's small files only (labels,
verification, L1/L2/L3, metrics, load) — the bundle most readers actually want, since
the full set is ~330 GB. Each run also gets a generated RUN-INFO.txt (what broke,
when, what is in the folder) so a reader never has to consult external docs.

Inventory findings worth keeping: 109 runs = 93 labeled faults + 12 `normal` controls
+ 4 `lttng_only` overhead runs. The 16 without ground_truth.json are correct by design
(no fault = no label). 4 sockshop anomaly_mem calibration variants (bigheap/fix/swap/
vmhang) have L2 but no L1/L3 — derivation gap, not data loss; flagged in manifest.
Working-set metrics dirs verified identical to the archived ones (432 files), so the
repack sources them from /scratch (on disk, no extra extraction).

Execution: SLURM whole-node job (2167926), 26 families, PAR=8, pigz -p 20, staging in
/dev/shm (566 GB, node has 755 GB RAM — the 8 largest expand to ~250 GB, checked before
letting it run). Resumable: repack_family.sh skips families that already have a
.sha256. Scripts in /scratch/yuvraj17/reorg/. A separate verify job proves each new
archive is a strict SUPERSET of the old one (every original path still present).

### Result (same day)
Repack job 2167926 COMPLETED in 24m33s: 26/26 families, 0 failures. Verify job 2168499
(after a first submit was silently killed by SIGPIPE from `sbatch | head -1` — never pipe
sbatch): **26/26 PASS, 0 paths lost** — 195,914 original paths all present, +51,548 added
(L2 + metrics/ + load.csv + RUN-INFO.txt per run). Release = 316 GB, 27 archives, 110 runs
at /scratch/yuvraj17/stratatrace-v1/, plus stratatrace-lite.tar.gz at only **196 MB** for
all 110 runs (the bundle to attach to a paper).

Two data findings worth remembering:
- **Train Ticket has no verification.png at all** (Sock Shop 27/27, TT 0/49). verify_injection.py
  queries a LIVE Prometheus, so plots cannot be regenerated from the archived metrics without a
  new script. verification.json (the actual pass/fail check) exists for both apps. README states
  the gap; manifest has has_verif_png.
- **`gate01`** — a Phase-0 smoke test — sits inside sockshop/normal.tar.gz and was being counted
  as a healthy control. Reclassified run_type=smoke-test (not deleted). Honest counts:
  **93 fault runs**, 12 controls, 4 overhead, 1 smoke test = 110.
Originals in /project untouched (read-only inputs). Packaging scripts committed to
transfer/release/ so this is reproducible, not a one-off.

## Train Ticket verification plots regenerated offline (2026-08-20)
Yuvraj asked whether the missing TT verification.png could be made. Yes — the blocker was
only that `verify_injection.py` queries a LIVE Prometheus; the underlying data was never
missing (each run archives 543 metric files). Wrote
`microservice-lttng-data-collection-scripts/plot_verification_offline.py`: a small evaluator
for the exact PromQL subset the catalog uses (rate/increase/min/avg, scalar arithmetic,
`=`/`=~` matchers — only 12 distinct check shapes across all 43 TT runs), reusing the original
plot styling.

**Validated against Sock Shop runs that were plotted from real Prometheus.** Shape matches
closely, but this exposed a genuine limit worth recording: **the archives contain no pre-run
history**, so `rate()`'s 1-minute lookback is truncated at the start and the first ~60 s reads
high (e.g. anomaly_cpu baseline 42.7 computed vs 27.8 stored). Handled by shading that region
grey + a footnote on every plot, and by NEVER recomputing the stored means — verification.json
keeps its original Prometheus numbers; only `impact_plot` + `impact_plot_source` are added.

**Refused 3 plots on purpose.** For tt_svc_mem_cap the *canonical* check is
`min(container_spec_memory_limit_bytes{...})` and that metric file was never archived; the only
surviving check (`order_oom_kills`) is flat zero, which would read as "nothing happened". The
tool now skips when the canonical check is unreproducible (`--allow-noncanonical` overrides).
Result: 40/43 TT runs plotted; every labeled fault run in the dataset now has a plot except
those 3. TT archives repacked (job 2170750, 12/12 OK) so the plots ship inside each run.

## Why sockshop has 4 extra anomaly_mem runs and TT has none (asked by Yuvraj)
Not a gap — calibration debris. On 2026-07-31 host-memory exhaustion took four attempts in one
evening, each saved as a run: swap_r1 (3 workers, `--vm-bytes %`) and fix_r1 (4 capped workers)
both FAILED the MemAvailable gate (verification_status=unconfirmed, 0.63/0.76 vs the 0.15 gate);
bigheap_r1 passed metrics but the cgroup `--memory` cap trapped reclaim inside the memcg → ZERO
`mm_vmscan_*`, losing the kernel signature that is this fault's winning modality; vmhang_r1
(single UNCAPPED worker, 88% RAM) fired both signals. The winner went into `anomaly_mem.sh`, and
the real 3 repeats were collected next morning with identical params. Train Ticket was ported
five days later (runs 2026-08-05) and simply called the calibrated recipe — same
`vm-hang(single,uncapped)` stressor, resized to 22.5 GB/35% because 40 Java services already
hold a lot of RAM. The search only had to happen once.
**Open question for Yuvraj:** fix_r1 and swap_r1 are verified FAILURES but carry ground_truth,
so the manifest counts them as fault runs (93). Reclassifying them `calibration` (as was done
for gate01 → smoke-test) would give an honest 91. NOT done — awaiting his call.
