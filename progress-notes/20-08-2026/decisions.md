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
