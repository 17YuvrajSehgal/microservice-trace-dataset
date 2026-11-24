# 24-11-2026 - decisions

## v3 collection: first VM

**Process (decided by the user).** One fault family at a time, one run at a time. After each
run the data goes to Trillium and is verified there before the next run starts. One VM first;
several in parallel only when the single-VM loop is trusted.

**Account.** `gcp200106@gmail.com`. It cannot see the old `teleeporter` project. It owns
`project-ba99825a-df02-4405-af4` ("My First Project"), billing account open, Compute API on.
Three stopped VMs of other work are in it (`kt-measure-1/2/3`, 200 GB disks each); not touched.

**Quota (measured).** CPUS_ALL_REGIONS 24, us-east1 SSD_TOTAL_GB 400, N2_CPUS 200. So one
Sock Shop VM (12) or one Train Ticket VM (16) fits, two Sock Shop VMs fit exactly, and Sock
Shop + Train Ticket together (28) do not. Parallel collection needs a quota increase, which the
user must request.

**VM `stratatrace-ss-v3`.** us-east1-d, n2-custom-12-40960, 200 GB pd-balanced boot, Ubuntu
24.04.5 - the v2 Sock Shop shape. Differences from v2, both deliberate or unavoidable:
- kernel 7.0.0-1017-gcp (v2: 1011 and 1014). A fresh image gets the current kernel.
- no 1 TB archive disk. Runs are shipped one at a time, so nothing accumulates; the trace was
  always written to the boot disk, so the runs are not affected.
- SSH: the WSL key `~/.ssh/google_compute_engine`, user `17yuv`, put in instance metadata.
  From Git Bash the key path must be protected with `MSYS_NO_PATHCONV=1`.

**Bootstrap and gate.** `vm_bootstrap.sh`: 233 kernel tracepoints, stack up, BOOTSTRAP OK. The
workload image step failed on the known docker-group issue and was rerun in a fresh login
shell. `run_gate.sh gate01`: six OK (trace 41 spans, logs 4,079 lines, load 454 requests,
metrics 524 series, kernel 1,710,390 events, clock drift 0.000 ms).

**Not done yet.** The restricted pull key for Trillium, one end-to-end dry run of the
collect -> pull -> verify -> delete loop, the Train Ticket VM, and recipes for the new families
(none of the 70 candidates has one).
