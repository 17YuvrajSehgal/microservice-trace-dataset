# Release packaging (dataset → publishable form)

Turns the scattered collection output into a release where **every run folder is
self-contained**. Reads the `/project` archives; never writes to them. Nothing is
ever deleted.

## What was scattered, and what these scripts fix

| Problem | Fix |
|---|---|
| `kernel_l2.jsonl` only existed in the `/scratch` working set (derived after the archives were built) | copied into each run |
| `metrics/` and `load.csv` sat *beside* the run as `<run>_metrics/` and `<run>_load.csv`, and in a separate `_aux_metrics_load.tar.gz` | moved inside each run |
| A reader had to fetch 3 places to get one complete run | one archive per fault type; each run complete |
| No per-run explanation | generated `RUN-INFO.txt` in every run |

## Order to run

```bash
python3 inventory.py                       # what exists where (writes inventory.csv)
sbatch repack_all.sbatch                   # rebuild all families self-contained (resumable)
bash   finalize.sh                         # manifest.csv, per-app READMEs, lite bundle, checksums
sbatch verify_all.sbatch                   # prove each new archive ⊇ the old one
```

Single family, for testing: `bash repack_family.sh sockshop anomaly_cpu 12`

## Notes

- Output goes to `/scratch/yuvraj17/stratatrace-v1/` (not `/project` — that has
  only ~700 GB free and the release is ~330 GB). Move it once verified.
- `repack_all.sbatch` stages in `$SLURM_TMPDIR`, which on Trillium is `/dev/shm`
  (RAM, 566 GB on a 755 GB node). With `PAR=8` the eight largest families expand
  to roughly 250 GB — check this before raising `PAR`.
- Resumable: a family with a `.sha256` next to its archive is skipped.
- `enrich_run.py` is stdlib-only, so no venv is needed on the compute node.
