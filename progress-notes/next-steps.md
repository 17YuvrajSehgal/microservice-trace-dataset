# Next steps

_Updated 15 September 2026._

## Where things stand

The 25 contaminated code-defect runs are re-collected and verified. **26 of 26 usable**
(25 campaign runs + 1 proof run). Baseline no longer contains a container restart.

**These 26 runs exist only on the collection VM.** They are not on Trillium yet. That is the
one thing worth acting on quickly.

The rest of v2 (303 runs, 1.18 TB) is on Trillium. Inventory:
`blueprints/docs/DATASET-v2-INVENTORY.md`. Known problems: `CAMPAIGN-ISSUES.md`.

## The result from this collection

Two of the five code defects DO move a metric. Three do not. See
`progress-notes/15-09-2026/decisions.md` and CAMPAIGN-ISSUES 21.

| family | baseline | injection | recovery | reads as |
|---|---|---|---|---|
| `code_lock_across_io` | 106.5 | 262.2 | 262.7 | ramp only |
| `code_n_plus_one` | 104.1 | 255.9 | 255.0 | ramp only |
| `code_unbounded_cache` | 99.8 | 245.9 | 247.2 | ramp only |
| `code_event_loop_block` | 102.8 | **34.3** | **122.4** | real |
| `code_serial_awaits` | 93.6 | **50.5** | **132.4** | real |

Trace volume agrees independently: the two visible families produced 14–15 GB per family, the
three invisible ones 26–33 GB. Throughput fell, so fewer kernel events.

## Next, in order

### 1. Get the 26 runs off the VM — BLOCKED, needs you

`transfer/push_to_trillium.sh` is ready and pigz is installed, but the new VM has **no SSH key
for Trillium**. SciNet needs key + MFA, so this needs you:

```bash
# on the VM
ssh-keygen -t ed25519 -f ~/.ssh/trillium -N ""
cat ~/.ssh/trillium.pub          # add this at https://ccdb.alliancecan.ca -> Manage SSH Keys
```

Then the push is one command:

```bash
DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=sockshop \
    ./push_to_trillium.sh
```

114 GB. GCP egress is roughly $14. Verify after with `./push_to_trillium.sh --verify`.

### 2. Stop the VM once the transfer is done

It bills about $0.50/hr while running. The disk persists when stopped.

### 3. Rebuild packs on Trillium so `baseline_quiet` can run over the new runs

### 4. Still to re-collect — both need a decision, neither is quick

| what | runs | why it is not quick |
|---|---|---|
| `svc_net` on Train Ticket | 4 | needs a Train Ticket stack; not deployed on this VM |
| `tt_slow_db_subtle` r3 | 1 | same |
| `dns_delay` r4 | 1 | no `dns_delay` runs exist on this VM, so re-running the family collects 5, not 1 (~45 min) |

Train Ticket code defects remain a separate decision — real work, worth it only if we want
those five faults in the paper for both apps.

## Open questions, carried forward

1. The sigma test cannot fire on the two visible families. The load ramp inflates
   `baseline_std` (CAMPAIGN-ISSUES 20), so verdicts rest on direction + fraction plus the
   recovery window.
2. Settled catalogue rate is ~130/s in front-end-defect runs but ~250/s in catalogue-defect
   runs under the same load. Within-run comparisons are fine. **Do not compare absolute rates
   across the two groups** until this is explained.

## Older items still open

- H1: with/without agent comparison
- H2: parent/child blueprint tree
- I1: `service-memory-cap` vs `anomaly_mem`
- `explanation.txt` and `recommended_action.txt` are declared by blueprints but written by
  nothing
