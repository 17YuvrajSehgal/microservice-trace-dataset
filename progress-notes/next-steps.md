# Next steps

_Updated 6 September 2026, after the v2 collection campaign finished._

## Where things stand

303 runs collected and archived (Sock Shop 169, Train Ticket 134), 1.18 TB, four modalities in
every run, 302/303 kernel traces with zero event loss. Full inventory:
`blueprints/docs/DATASET-v2-INVENTORY.md`. Known problems: `CAMPAIGN-ISSUES.md`.

Both VMs are still RUNNING. Nothing outstanding needs them except the transfer itself and any
re-scoring against live Prometheus — and the Prometheus TSDBs are already snapshotted to
`/mnt/archive/prometheus/` on each VM and copied locally, so even that is no longer a reason to
keep them up.

## Next, in order

1. **Confirm the Trillium destination and capacity.** 1.18 TB has to fit `/scratch` alongside v1.
   `push_to_trillium.sh` now refuses to run without an explicit `DEST_ROOT`, on purpose — v2
   reuses every v1 recipe name.

2. **Push, per application.** Resumable; it skips archives that already exist.

       bash transfer/push_to_trillium.sh --setup-master        # once, interactive (MFA)
       DEST_ROOT=<v2 root> SRC=/mnt/archive/runs APP=sockshop    bash transfer/push_to_trillium.sh
       DEST_ROOT=<v2 root> SRC=/mnt/archive/runs APP=trainticket bash transfer/push_to_trillium.sh
       DEST_ROOT=<v2 root> SRC=/mnt/archive/runs APP=sockshop    bash transfer/push_to_trillium.sh --verify

3. **Stop the VMs** once `--verify` passes for both. Disks persist.

4. **Decide on the 103 Train Ticket load CSVs** (issue 14). Not recoverable; re-collecting is
   ~620 GB and ~a day for one modality of four. Depends on whether the ablation study needs a
   client-side view on Train Ticket. Hits `anomaly_net` hardest — the CSV was its stated fallback.

5. **Write the offline re-scoring adapter** (issue 3): read each bundle's own metrics export
   instead of live Prometheus. 440 metric files per run already exist and nothing reads them.
   Then settle the 10 outstanding Train Ticket verdicts (`slow_db` ×5, `svc_net` ×5) — remembering
   `svc_net`'s candidates rise uniformly ~2.1x across unrelated services, which reads as load
   drift, so fault and drift must be separated before anything is registered.

6. **`fault_catalog.md` pre-registration for the 15 new v2 families.** Never done; predictions
   froze at the campaign start. A research decision, not a chore: pre-registration after seeing
   the data is not pre-registration, so the honest options are to register them as exploratory or
   to state plainly when each prediction was written.
