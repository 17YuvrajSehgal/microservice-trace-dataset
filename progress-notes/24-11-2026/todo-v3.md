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
| 3 | `disk_full` (C1) | `faults/disk_full.sh` | done, on Trillium, checksums verified |
| 4 | `port_exhaustion` (D1) | `faults/port_exhaustion.sh` | done, on Trillium, checksums verified |
| 5 | `pid_limit` (H2) | `faults/pid_limit.sh` | calibrated on orders (the only service that starts threads at steady load); check run started 02:00 UTC, 25-11 |
| 6 | `db_table_lock` (E6) | to write | after 5 |
| - | `thread_pool_exhaustion` (E3) | - | postponed: the pool size of the Java services can only be set at start-up, so the fault would also be on in the baseline. Needs a runtime switch (JMX) first |

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
| 26 | `svc_cpuset` | `cpu_confine.py` | finds 5 of 5 on the first try, reversed comparison quiet; false-alarm check deferred by the user |
| 27 | `disk_full` | `new_errors.py` | finds 5 of 5 in the slice that contains a crash (30 fallocate calls returning ENOSPC); quiet between crashes; false-alarm check deferred |
| 28 | `port_exhaustion` | `new_errors.py` (same tool) | finds 5 of 5 in both fault slices (connect returning EADDRNOTAVAIL, 46-67% of the catalogue's connects); false-alarm check deferred |
| 29 | `pid_limit` | `new_errors.py` should cover it (clone returning EAGAIN) | when family 5 is on Trillium |

For each: one baseline slice and one fault slice per run from a temporary decompressed copy;
the tool must find 5 of 5 and name only the faulty container; the reversed comparison must be
quiet. No README or RESULTS file until the false-alarm check has run.

## Things that can stop the chain

- The Trillium login expires about 8 hours after the user's last login (about 03:45 UTC on
  25-11). After that: keep collecting, leave finished families on the VM, stop the VM when
  the collection queue is empty.
- Claude Code may stop a local monitor when the laptop is low on memory. The runs on the VM
  are not affected; the state is in this file and in `~/campaign_manifest.csv` on the VM.

## State at 23:55 UTC, 24-11

- Trillium is unreachable (control socket gone). Everything that needs it waits for the user's
  login: moving `disk_full`, testing blueprint 26, writing blueprint 27.
- The VM keeps collecting. Finished families stay on its disk (150 GB free; a family is about
  28 GB packed).
- To resume after login: (1) `pull_from_vm.sh` for `disk_full` (and any later family) with the
  VM's current IP, verify, checksum, delete on the VM; (2) upload `26_svc_cpuset/tools` and run
  `work/v3bp26_all.sh` (script is in the session scratchpad as tr10.sh; it cuts 10 s
  sched slices per run and runs `cpu_confine.py` both ways).

## State at 00:45 UTC, 25-11

- Trillium is back (user logged in). `disk_full` and `port_exhaustion` move to Trillium together once run 5 of `port_exhaustion` is done - not during a traced run, the pull would load the VM.
