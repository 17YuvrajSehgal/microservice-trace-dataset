# 27-11-2026 decisions

## Group 5 collection

- **First start failed on my bug.** The recipe generator wrote doubled backslashes into `EXPECTED_BLAST_RADIUS`, so `ground_truth.json` was invalid and the verify step skipped the run. Fixed in 08f7005. The bad run was deleted on the VM and never shipped.
  - Lesson: `bash -n` does not catch this. Check that a new recipe's ground truth parses as JSON before the chain starts.
- **Collected:** `code_fd_leak` 5/5 confirmed, `code_zombie_procs` 5/5 (no metric signature, as registered), `code_blocking_wait` 4/5 confirmed.
- **`code_blocking_wait` run 5 was borderline and is replaced by a new run.**
  - Why borderline: its baseline was slow (front-end span p95 184 ms; the normal range over all v3 runs is 113 to 148 ms). The fault window was like the other runs (201 ms).
  - The discarded run's numbers: metric p95 baseline 0.2255, injection 0.2376; spans p50 82.4 to 88.8 ms.
  - This is a re-collection after a failed check, as the collection rules say. It must be reported with the dataset: one run replaced, reason a noisy baseline.
- **The front-end p95 metric tops out near 0.235 to 0.245 s in the fault window** (histogram buckets), while baselines range from 0.17 to 0.23 s. So the metric target for this family has little room. The spans are the better evidence for it.
- **Databases keep growing over the campaign** (25,853 customers, 38,039 orders on 27-11). Baselines are not slower than on 26-11, but this should be watched, or the databases reset between groups.
