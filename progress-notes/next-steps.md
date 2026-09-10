# Next steps

_Updated 9 September 2026. Waiting on Trillium, back on 10 September._

## Where things stand

303 runs collected and archived (Sock Shop 169, Train Ticket 134), 1.18 TB, four modalities in
every run, 302/303 kernel traces with zero event loss. Full inventory:
`blueprints/docs/DATASET-v2-INVENTORY.md`. Known problems: `CAMPAIGN-ISSUES.md`.

Both VMs are still RUNNING. Nothing outstanding needs them except the transfer itself and any
re-scoring against live Prometheus — and the Prometheus TSDBs are already snapshotted to
`/mnt/archive/prometheus/` on each VM and copied locally, so even that is no longer a reason to
keep them up.

## Next, in order

Everything below is ready. Nothing is blocked except by the cluster.

### When Trillium is back (10 Sept), do this first

    wsl.exe -d Ubuntu -- bash -lc "ssh -fNM trillium"     # one Duo login, from the laptop
    cd /scratch/yuvraj17/stratatrace/repo && git pull
    sbatch blueprints/lib/cluster-v2_packs.sbatch blueprints/lib/tasks-v2-uncovered.txt

That builds 156 evidence packs for the fault families with no blueprint. About 45 minutes on one
node. It skips packs that already exist, so it is safe to resubmit.

The previous job (2280376) was cancelled while the cluster was in maintenance.

### Then, in order

1. **Measure before writing anything.**

       python blueprints/lib/derive_v2_thresholds.py --packs <packs> --tasks <tasks-v2-uncovered>

   Add the new families to `RULES` in that script first. It reports, per signal per application,
   whether a cut separates the fault from every other family. A signal that works on one
   application is reported as failing, never averaged.

2. **Write blueprints only for what separates.** A fault with no separating signal is a result to
   report, not a gap to hide.

3. **The five likely-easy ones**, because their signals are already extracted:
   `resource_abuse` (thief_cores), `lock_contention` and `deadlock` (futex shape), `anomaly_mem`
   (interrupt time), the five `code_*` (endpoint slowdown).

4. **The five needing the new probe**: `fork_storm`, `fd_exhaustion`, `conn_pool_exhaustion`,
   `data_exfiltration`, `dns_delay`, `priority_inversion`. `process_probe.py` is written and
   verified on a real run.

5. **Run the with/without agent comparison on v2.** Everything measured so far is the rule engine.
   This is what the demo needs.

6. **The parent/child blueprint hierarchy.** Agreed at the 2 Sept meeting, never added to the task
   list, never started.

7. **fault_catalog.md pre-registration** for the 15 new families.

### Out of scope, decided and measured

`dependency_outage`, `queue_backlog` and `error_storm` cannot be seen in kernel traces. They
belong on the out-of-scope list, not the backlog. That leaves 16 problems to cover, not 19.

### Known limits to carry

- `service-cpu-throttle` and `datastore-wait` cannot be re-derived: Train Ticket has zero
  confirmed runs for `svc_cpu_cap` or `slow_db`.
- Train Ticket reports all ~40 Java services as one process name, so per-process signals are
  diluted there. Flow-based signals (endpoint latency) are not.
- Baseline host load drifted 4.6x during collection, so absolute levels partly measure when a run
  happened. Within-run ratios are unaffected.
