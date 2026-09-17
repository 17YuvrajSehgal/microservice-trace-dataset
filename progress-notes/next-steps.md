# Next steps

_Updated 17 September 2026, end of session._

## Read this first

**10 runs exist ONLY on the stopped Train Ticket VM's archive disk.** 8 `error_storm` + 2
`svc_net`. They are not on Trillium. The disks persist while the instance is stopped, so nothing
is at risk today, but this is the same single-copy exposure that made the v1 loss possible.

Getting them to Trillium is the first job tomorrow, before collecting anything else.

## The VM

| | |
|---|---|
| name | `stratatrace-tt`, us-east1-d, `n2-standard-16` |
| state | **TERMINATED** (stopped cleanly; no partial bundles, LTTng sessions destroyed) |
| disks | 200 GB boot + 1 TB archive, both `READY`, both persist |
| cost while stopped | disks only, roughly $60/month |
| cost while running | about $0.78/hour |

**Its external IP WILL CHANGE on restart.** Re-read it and pass it to `pull_from_vm.sh`:

```bash
gcloud compute instances start stratatrace-tt --zone=us-east1-d --project=teleeporter
gcloud compute instances describe stratatrace-tt --zone=us-east1-d --project=teleeporter \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

## Tomorrow, in order

### 1. Finish the 3 remaining `svc_net` runs

r3, r4, r5. The driver is already on the VM at `~/collect_sn.sh` and is resumable — it skips runs
whose bundle exists, so just re-run it. It also re-runs its own pre-check and **aborts if
`ts-basic-service` is not carrying traffic**, which is the condition that ruined the originals.

```bash
setsid ~/collect_sn.sh > ~/collect_sn2.log 2>&1 &
```

About 15 min/run, so ~45 minutes.

### 2. Prove the fault is in the new `svc_net` traces

**This is the step that matters, and the metric verdict does not answer it.** `svc_net`'s target
is `rate(container_network_transmit_bytes_total)` with `direction: decrease`, which is BACKWARDS —
packet loss causes retransmission, so transmitted bytes go UP (measured: 15938 -> 31517). Both
collected runs already read `unconfirmed` for that reason and it means nothing.

Run the kernel-trace check instead, which is validated on TT traces (it reproduced r1's 42.9%):

```bash
python3 blueprints/lib/net_loss_signature.py --ctf <run>/kernel/kernel \
    --gt <run>/ground_truth.json --out <run>_netloss.json
```

Read `signature.worst_retrans_pct` and `signature.n_impaired`. Expect ~4% loss and impaired
veths; r1 of the old family is the reference at 42.9%.

### 3. Then fix the `svc_net` target

Almost certainly the same shape as `error_storm` and `anomaly_net` on TT: Sock Shop's target is
`carts_p95_latency`, and **Train Ticket exposes no latency histogram**, so metrics are
structurally blind to netem there. If the traces show loss, mark `expected_to_fail` and record the
retransmission percentages as the evidence. Do not adopt a target until it passes a specificity
check across families — that is what caught the `slow_db` near-miss.

### 4. Set up the Trillium pull key on this VM

The pull key was never installed here — it only ever existed on the Sock Shop VM, which is
deleted. Repeat the `transfer/README.md` procedure: generate a key on Trillium, install
`transfer/export_recipe.sh` to `~/bin/` on the VM, and add the forced-command line to
`~/.ssh/authorized_keys`. **That last step needs you** — the classifier blocks me from editing
`authorized_keys`.

### 5. Pull, verify, delete

```bash
VM_HOST=<new ip> DEST=/scratch/yuvraj17/stratatrace/v2/trainticket-recollected-20260917 \
    ~/bin/pull_from_vm.sh
sbatch --array=0-N transfer/verify_archives_array.sbatch     # one archive per node
```

Then delete the instance **and** the archive disk (`auto-delete=no`, so it survives otherwise).

## Still open, not started

- **`svc_net` r4** of the old family was never re-analysed for loss (r1/r2/r3/r5 were).
- The **103 Train Ticket runs with no client-side load CSV** — a research call, not a defect.
- **1 lossy run**, `tt_anomaly_disk_aggressive_steady_r4` (~0.25% discarded), kept deliberately.
- **Train Ticket code defects** (25 runs) — the only way those five faults satisfy the
  two-application rule. Today's Node-vs-Go finding makes a third runtime genuinely interesting.
- `explanation.txt` / `recommended_action.txt` are declared by blueprints and written by nothing.
- H1 with/without agent comparison; H2 parent/child blueprint tree.
