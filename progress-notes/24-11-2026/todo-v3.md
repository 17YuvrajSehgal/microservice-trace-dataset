# v3 collection and blueprints - working todo (user away from 24-11-2026, evening)

Rules given by the user, in force while unattended:
- One family at a time; run 1 is a check run; every run is quality-checked; bad runs are deleted.
- Move a family to Trillium only when all 5 runs are accepted; verify checksums there; then
  delete it from the VM. Stop the VM whenever nothing is being collected.
- Blueprint work on Trillium uses the LOGIN NODE only, at low priority. NO SLURM job (the
  false-alarm check for the new blueprints is deferred until the user asks).
- No API spend.

## Collection

| # | family | recipe | state |
|---|---|---|---|
| 1 | `code_lock_contended` | `faults/code_lock_contended.sh` | done, on Trillium, checksums verified |
| 2 | `svc_cpuset` (A1) | `faults/svc_cpuset.sh` | done, on Trillium, checksums verified |
| 3 | `disk_full` (C1) | `faults/disk_full.sh` | run 1 accepted; runs 2-5 being collected |
| 4 | `port_exhaustion` (D1) | to write | next: recipe, calibration, check run, 4 more runs |
| 5 | `thread_pool_exhaustion` (E3) | to write | after 4 |

Steps for each family, in order:
1. Write the recipe; calibrate on the VM (what really happens, does it recover, which metric sees it).
2. Check run (run 1): six audit lines, no kernel loss, verification or a family-specific proof,
   quality gate, the fault visible in spans or logs, clean-up state of the stack.
3. Runs 2-5 with the monitor; the driver stops the family at the first bad run.
4. Pull to Trillium, count runs, extract, `sha256sum -c` per run. Only then delete on the VM.
5. Notes in `decisions.md`; commit and push.

## Blueprints (login node only)

| # | family | tool | state |
|---|---|---|---|
| 25 | `code_lock_contended` | `inside_wait.py` | finds 5 of 5; false-alarm check deferred by the user |
| 26 | `svc_cpuset` | `cpu_confine.py` | in progress: write the tool, test on the 5 runs |
| 27 | `disk_full` | to write (ENOSPC returns + abort + restart) | when family 3 is on Trillium |
| 28 | `port_exhaustion` | to write | when family 4 is on Trillium |

For each: one baseline slice and one fault slice per run from a temporary decompressed copy;
the tool must find 5 of 5 and name only the faulty container; the reversed comparison must be
quiet. No README or RESULTS file until the false-alarm check has run.

## Things that can stop the chain

- The Trillium login expires about 8 hours after the user's last login (about 03:45 UTC on
  25-11). After that: keep collecting, leave finished families on the VM, stop the VM when
  the collection queue is empty.
- Claude Code may stop a local monitor when the laptop is low on memory. The runs on the VM
  are not affected; the state is in this file and in `~/campaign_manifest.csv` on the VM.
