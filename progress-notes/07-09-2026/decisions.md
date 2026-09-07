# 7 September 2026 — decisions

## Context

v2 was on Trillium and verified. Today: make it usable, stop paying for GCP, and settle where the
copies live.

---

## 1. Found the access route back — and why the obvious one cannot work

Claude could drive Trillium "until two days ago". Why it stopped is worth recording, because the
failure looks like a permissions problem and is not.

**Git Bash cannot use an ssh ControlMaster across processes.** `ssh -O check` succeeds — the master
is alive and answering — but opening a session fails:

    mux_client_request_session: read from master failed: Connection reset by peer

Session multiplexing passes file descriptors over the Unix socket, and MSYS's socket emulation does
not carry that between separate runtimes. It worked GCP→Trillium throughout the push because those
masters lived on Linux VMs.

**The route that works is WSL**, where `~/.ssh/config` already had `trillium` and `nibi` aliases
with `ControlMaster auto`:

    wsl.exe -d Ubuntu -- bash -lc "ssh -o BatchMode=yes trillium '<command>'"

**Also measured: Alliance MFA has no grace window.** A direct connection minutes after a successful
Duo login was still refused. A registered key only ever buys
`Authenticated using "publickey" with partial success`. So a human must open the master — but check
for a live one before asking for another.

Recorded as a memory, not only here: it is environment knowledge that outlives this project.

## 2. Chained the decompression instead of restarting the extraction

The suggestion was to restart as one combined job rather than run two. Right instinct, wrong
mechanism: the extraction was already **running**, and cancelling it would have sent it back to a
queue it had already waited in.

Used `sbatch --dependency=afterok:<jobid>` instead. Costs nothing, starts the instant extraction
succeeds, loses no work. **`afterok` and not `afterany`** deliberately — decompressing a partially
extracted tree would produce a working copy that looks finished and is not.

Both finished well inside their allocations: 19 minutes to extract, 16 to decompress, on one
192-core node.

## 3. "Gunzip the CTF" was wrong by two orders of magnitude

I framed the decompression as being about the kernel traces. Scanning the extracted tree first said
otherwise:

| | count |
|---|---|
| kernel `channelN_N.gz` | ~4,000 |
| per-run Prometheus export (`node_load1.json.gz`, `up.json.gz`, …) | **~142,000** |

Each run's ~440 metric series is its own gzipped JSON. Doing "the traces" would have left **97% of
the compressed files in place** — the opposite of the instruction. The instruction was "everything",
and taking it literally rather than as shorthand for the part I had in mind is what caught it.

**The general lesson:** I described the work from the part of it I already had in mind. One scan of
what was actually on disk corrected it. The same reflex found the missing load CSVs yesterday.

## 4. Verified by reading a trace, not by counting files

`--verify` reporting 303 runs and zero `.gz` proves `tar` and `pigz` exited cleanly. It does not
prove the data is usable. Opening a trace with babeltrace 2.1.2 does:

    [04:12:53.521030424] net_dev_queue: { cpu_id = 2 }, { pid = 18364, procname = "conn62" },
       { skbaddr = 0xFFFF8D58E9922CE8, len = 126, name = "eth0", ... saddr = [172,18,0,10] ... }
    [04:12:53.521030652] (+0.000000228) power_cpu_idle: { cpu_id = 0 }, ...

Full network-header decoding, sub-microsecond deltas, and `power_cpu_idle` — the tracepoint that
only became available on the v2 VMs.

One mistake in doing it: the first verification asked babeltrace to count **every** event in a
trace, which reads the whole thing on a shared login node. Killed it and re-ran a metadata-only
check. Reading two events proves the same thing as reading twelve million.

## 5. Deleted the GCP VMs — Trillium is now the only copy

Both instances and all four disks. The 1 TB archive disks had `autoDelete=False`, so they would have
survived the instance delete and kept billing silently; removed explicitly. Nothing of this project
remains in `teleeporter`; cost is zero.

**Updating the docs mattered more than the deletion itself.** `CLAUDE.md` described the disks as "a
second copy" and the inventory listed `stratatrace-ss:/mnt/archive` as a location. Both were true
that morning. Left alone, someone would later act on a fallback that no longer exists.

The decision came after declining a Nibi copy, declining a GCS Archive copy (~$1.50/month), and
finding Trillium `/project` short by ~73 GiB. Stated once for the record and not reopened: the
archives and the working copy sit on the same filesystem, so they protect against a bad extraction,
not against losing `/scratch`.

## Where it ended

| | |
|---|---|
| archives | Trillium `/scratch/yuvraj17/stratatrace/v2/` — 51 tarballs, 778 GB, verified 303/303 |
| working copy | Trillium `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/` — 303 runs, 831,475 files, 7.3 TB, zero `.gz` |
| Prometheus TSDBs, campaign logs | laptop, under `C:\workplace\` |
| GCP | deleted |

Scratch: 12 TiB of 25 TiB, 1,797K files of 10M.

## Still open (unchanged from 6 Sept)

- The 103 Train Ticket runs with no load CSV — not recoverable, ~620 GB to re-collect, and now a
  fresh VM as well.
- The offline re-scoring adapter, then the 10 uncalibrated Train Ticket verdicts.
- `fault_catalog.md` pre-registration for the 15 new families.
