# Next steps

_Updated 7 September 2026. Collection, transfer and extraction are all finished._

## Where things stand

303 runs collected and archived (Sock Shop 169, Train Ticket 134), 1.18 TB, four modalities in
every run, 302/303 kernel traces with zero event loss. Full inventory:
`blueprints/docs/DATASET-v2-INVENTORY.md`. Known problems: `CAMPAIGN-ISSUES.md`.

Both VMs are still RUNNING. Nothing outstanding needs them except the transfer itself and any
re-scoring against live Prometheus — and the Prometheus TSDBs are already snapshotted to
`/mnt/archive/prometheus/` on each VM and copied locally, so even that is no longer a reason to
keep them up.

## Next, in order

Everything left is research. No logistics outstanding.

1. **Decide on the 103 Train Ticket load CSVs** (CAMPAIGN-ISSUES issue 14). Not recoverable, and
   re-collecting now needs a fresh VM too, since the collectors are deleted. ~620 GB and about a
   day, for one modality of four. Hits `anomaly_net` hardest: the CSV was its stated fallback for
   a fault with no metrics signature.

2. **Write the offline re-scoring adapter** (issue 3): read each bundle's own metrics export
   instead of live Prometheus. Those exports are now decompressed and sitting in the working copy,
   and nothing reads them. Then settle the 10 outstanding Train Ticket verdicts (`slow_db` x5,
   `svc_net` x5) - remembering that `svc_net` candidates rise uniformly ~2.1x across unrelated
   services, which reads as load drift, so fault and drift must be separated first.

3. **`fault_catalog.md` pre-registration for the 15 new v2 families.** Never done; predictions
   froze at campaign start. Pre-registration after seeing the data is not pre-registration, so the
   honest options are to register them as exploratory or to state plainly when each was written.

4. **Start the modality-ablation study** - the point of all of this. The working copy is ready at
   `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/<app>/<recipe>/<run_id>/`, decompressed and
   babeltrace-readable.
