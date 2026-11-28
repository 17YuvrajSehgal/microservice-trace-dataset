# v4: the controlled tier

Small programs that have one problem each, in five languages, traced on the collection VM's host
with the same LTTng kernel profile as v2 and v3. Sock Shop and Train Ticket show the problems in a
realistic system; v4 shows them under control, across languages and runtimes, and adds problems
those applications cannot produce (a database deadlock, a slow consumer, an I/O stall).

## Layout

| path | what |
|---|---|
| `problems/<problem>/problem.sh` | the problem: settings, languages, how the fault is switched on and off |
| `problems/<problem>/<language>/` | the program: `c/main.c`, `go/main.go`, `java/Main.java`, `python/main.py`, `node/main.js` |
| `lib/collect_v4.sh` | one run: noise, program, kernel trace, fault, ground truth, check, package |
| `lib/noise.sh` | the same background activity in every run (a web server and client, gzip, sha256sum) |
| `lib/sampler.py` | one row of program and host numbers per second (`metrics.csv`) |
| `lib/verify_v4.py` | did the program's own stats move? (`verification.json`) |
| `lib/setup_vm.sh`, `lib/build_all.sh` | prepare the VM (toolchains, `/mnt/v4io`, Sock Shop stopped) and build |

## How a run works

Every program prints one stats line per second and does its normal work. The fault is switched
on either by a flag file the program watches (`/dev/shm/v4_fault`) or by an injector outside the
program (CPU hogs, `fsfreeze`). Timeline: 20 s settle, 60 s baseline, 90 s fault, 45 s recovery.

Every fault run has a **healthy twin**: the same program and noise, nothing switched on, and the
same window times in its ground truth. The twins are the negatives for false-alarm tests.

Runs land in `~/archive/runs/v4_<problem>/v4_<problem>_<language>_<fault|healthy>_r<n>/` and move
to Trillium with `transfer/pull_from_vm.sh` like v3.

## Rules (the same as v3)

- Register each problem's prediction in `fault_catalog.md` before its first run.
- Check one run per problem and language before the rest.
- The pilot problems: deadlock, lock_contention, priority_inversion, cpu_starvation, slow_consumer, io_stall.
