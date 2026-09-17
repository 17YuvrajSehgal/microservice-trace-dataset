# StrataTrace v2 — what was collected

**Collection finished 6 September 2026. Partly re-collected 15-16 September 2026.**
**304 runs** across two applications, four modalities each.

This is the inventory: what exists, how good it is, and what to be careful about.

> **Read this first if you are picking runs to work with.** 53 Sock Shop runs were retired on
> 16 Sept and replaced by 54 freshly collected ones. The retired copies are still on disk under
> `superseded-20260917/` and are **not** part of the dataset. See
> [the re-collection](#the-re-collection-15-16-september) before using anything under
> `v2/sockshop/`.

---

## Headline

| | Sock Shop | Train Ticket | total |
|---|---|---|---|
| runs | **170** | **134** | **304** |
| runs with all 4 modality dirs | 170 / 170 | 134 / 134 | **304 / 304** |
| **kernel traces without event loss** | **170 / 170** | **133 / 134** | **303 / 304** |

The single lossy run is `tt_anomaly_disk_aggressive_steady_r4` (2,481,855 discarded, ~0.25% of
that run). It is kept deliberately - see [caveats](#caveats-that-affect-analysis).

Every run carries: kernel CTF trace, OTLP spans, container logs, meta/clock anchors, and a
per-run Prometheus export (~440 metric series) alongside the bundle.

The client-side request CSV is **complete on Sock Shop and partial on Train Ticket (31/134)** -
see [the load CSV gap](#the-train-ticket-load-csv-gap). It is a fifth artifact, not one of the
four modalities; all four are complete in all 304 runs.

## How many runs can you actually build a blueprint from?

Measured 16 Sept. The test: all four modality dirs, a loss-free kernel trace, the fault
demonstrably present, and a baseline that is a reference rather than a second incident.

| | runs | |
|---|---|---|
| **fully usable** | **287** | no run-specific caveat |
| usable with a caveat | 11 | listed below |
| not usable as a positive | 6 | the injection did not take |

Fully usable, by verdict:

| app | `confirmed` | `no_metric_signature` | `normal` (reference) |
|---|---|---|---|
| Sock Shop | 133 | 21 | 10 |
| Train Ticket | 99 | 14 | 10 |

`no_metric_signature` counts as fully usable. The fault is present and was **measured** to have
no metric signature; for kernel-trace work those 35 runs are the most interesting ones, not the
weakest.

The 11 with a caveat:

| caveat | runs |
|---|---|
| baseline inherits the previous run's restart loop (issue 22) | `fd_exhaustion` x5 |
| effect below threshold, needs a human | `queue_backlog` r2, `tt_error_storm` x2, `tt_slow_db` r2, `tt_svc_net` r5 |
| kernel event loss ~0.25% | `tt_anomaly_disk_aggressive_steady_r4` |

The 6 that are not usable as positives: `tt_svc_net` x4 (produced 0% packet loss) and
`tt_error_storm` x2 (effect too weak). These need calibration and re-collection, not re-scoring.

## Verification verdicts

Of 284 fault runs (304 minus 20 fault-free `normal` reference runs), after the 15-16 Sept
re-collection and re-scoring:

| verdict | Sock Shop | Train Ticket | meaning |
|---|---|---|---|
| `confirmed` | 133 | 99 | the fault moved its pre-registered target metric |
| `no_metric_signature` | 21 | 14 | **measured** to have no metric signature; this is a finding |
| `borderline` | 1 | 4 | right direction and coverage, magnitude below threshold |
| `unconfirmed` | 0 | 6 | the injection did not take - re-collection, not re-scoring |
| `n/a` (normal runs) | 10 | 10 | nothing injected, nothing to verify |

**A verdict is QC metadata, not data.** `unconfirmed` means the *metric check* failed, not that
the fault did not happen - and twice now the check was the thing that was wrong. Each bundle
preserves its collection-time verdict as `verification.as-collected.json`.

**Two target families were corrected on 16 September** (CAMPAIGN-ISSUES 22 and 23):

- `fd_exhaustion` went 0/5 to 5/5. Its target summed eleven Prometheus series that look like one
  - cAdvisor mints a new series per container restart - so a `decrease` target read 98 -> 446.
  What the fault does is restart-loop the front-end, exactly 9 times per injection.
- `svc_cpu_cap` (TT) went 0/8 to 8/8 and `svc_mem_cap` 7/8 to 8/8, by scoring the **mechanism**.
  A cap fault records itself: `container_spec_cpu_quota` is absent until docker applies a quota.
  The old targets watched CPU usage fall on a service already idle at 0.00 cores.
- `slow_db` (TT) is now `no_metric_signature`, measured. A candidate replacement
  (`container_fs_writes_total` on mysql) dropped to 48% of baseline in 11 of 11 runs and
  recovered - and turned out to show the identical 0.48 in **every** family, so it measured the
  window, not the fault.

## Per-family counts

Both applications, identical unless noted. 5 repeats per family at `aggressive`/`steady`; the
intensity and workload studies add 3 more to selected families (hence 8s and 11s).

| family | SS | TT | notes |
|---|---|---|---|
| `normal` | 10 | 10 | fault-free reference (5 steady + 5 burst) |
| `anomaly_cpu` | 5 | 5 | |
| `anomaly_disk` | 5 | 5 | **not the same experiment on both** — see caveats |
| `anomaly_mem` | 8 | 8 | |
| `anomaly_net` | 8 | 8 | **SS re-collected 15 Sept** - baseline median retransmission now 0% |
| `dependency_outage` | 5 | 5 | |
| `error_storm` | 8 | 8 | |
| `noisy_neighbor` | 8 | 8 | |
| `queue_backlog` | 5 | — | TT has no message broker |
| `slow_db` | 11 | 11 | TT: `no_metric_signature`, measured (issue 23) |
| `svc_cpu_cap` | 8 | 8 | **ineffective on TT** — see caveats |
| `svc_mem_cap` | 8 | 8 | |
| `svc_net` | 5 | 5 | **TT: 4 of 5 produced no packet loss - needs re-collection** |
| `lock_contention` | 5 | 5 | new in v2; **SS re-collected 16 Sept**, 2/5 -> 5/5 confirmed |
| `priority_inversion` | 5 | 5 | new in v2 |
| `deadlock` | 5 | 5 | new in v2; **SS re-collected 16 Sept**, 4/5 -> 5/5 confirmed |
| `fd_exhaustion` | 5 | 5 | new in v2; **SS re-collected 16 Sept**, target corrected (issue 22) |
| `conn_pool_exhaustion` | 5 | 5 | new in v2 |
| `resource_abuse` | 5 | 5 | new in v2 |
| `data_exfiltration` | 5 | 5 | new in v2 |
| `fork_storm` | 5 | 5 | new in v2 |
| `nagle_delayed_ack` | 5 | 5 | new in v2 |
| `dns_delay` | 5 | — | TT sends no DNS at all — see caveats |
| 5 × `code_*` | 25 | — | patch Sock Shop's own Go/Node source |

**Coverage split:** 144 aggressive / 15 subtle / 10 none on Sock Shop; 109 / 15 / 10 on Train
Ticket. 155 steady / 14 burst and 120 / 14 respectively.

## Caveats that affect analysis

These are properties of the data, not defects to be fixed later. Full evidence in
[CAMPAIGN-ISSUES.md](../../CAMPAIGN-ISSUES.md).

**Three families are not the same experiment on the two applications.** Do not compare them
across applications without saying so:

- **`anomaly_disk`** — Train Ticket's own tracing writes ~176 MB/s of a 206 MB/s disk, so
  `stress-ng` adds only **+24 MB/s** there against **+80 MB/s** on Sock Shop. The instrument
  does not merely fail to see the fault; it limits how large the fault can be.
- **`svc_cpu_cap`** — `ts-travel-service` uses **0.0033 cores** against a 0.2-core cap, 60x
  headroom, because Train Ticket spreads 20 users across 40 services. The cap never binds.
- **`anomaly_net`** — no metrics signature on Train Ticket at all. netem adds *latency*, and
  Sock Shop's services expose a latency histogram while Train Ticket's do not. On Sock Shop the
  fault is still visible in the load-generator CSV and the kernel trace. **On Train Ticket that
  CSV is missing for all 8 runs** (below), leaving the kernel trace and spans as the only
  evidence there.

**`dns_delay` reaches only external lookups.** Container-to-container names are answered by
Docker's embedded resolver inside the netns. On Sock Shop the effect is a tail effect: p50 and
p95 read *better* than baseline while wall-clock time is 22x and 8% of requests fail. Train
Ticket sends **zero** DNS packets (Nacos discovery over HTTP), so the family is absent there.

**Two of the five code defects DO move a metric; three do not.** Measured 15 Sept on the
re-collected runs, using the recovery window as the control (identical container image in both
windows, only the `/dev/shm` flag differs):

| family | baseline | injection | recovery | reads as |
|---|---|---|---|---|
| `code_lock_across_io` | 106.5 | 262.2 | 262.7 | load ramp only |
| `code_n_plus_one` | 104.1 | 255.9 | 255.0 | load ramp only |
| `code_unbounded_cache` | 99.8 | 245.9 | 247.2 | load ramp only |
| `code_event_loop_block` | 102.8 | **34.3** | **122.4** | real |
| `code_serial_awaits` | 93.6 | **50.5** | **132.4** | real |

Where injection equals recovery, nothing happened. Where the rate falls and returns, the fault
is real. **The split is Node vs Go**: both visible families are front-end Node defects that stall
a single-threaded event loop, so catalogue stops being called. The three invisible ones are Go in
catalogue, where concurrency absorbs a per-request slowdown and offered throughput holds. Same
class of bug, opposite modality outcome.

Trace volume agrees independently: the two visible families produced 14-15 GB per family against
26-33 GB for the three invisible ones.

This supersedes the earlier claim that all five shared one signature and that the container
restart was inseparable from the defect - the restart was a collection bug (issue 17), fixed.

**Bounded metrics are blind to faults our collection contends for.** LTTng writes ~53 MB/s
continuously on Sock Shop — exactly the measured baseline of `node_disk_written_bytes_total` —
so `node_disk_io_time_seconds_total` sits near saturation before any fault starts. Use unbounded
counters (operations, bytes, queue depth) for resource faults.

**Ring buffer size differs by application and by family**, and is recorded in each run's meta
snapshot. Sock Shop: 256 MB/CPU throughout. Train Ticket: 384 MB/CPU for `anomaly_mem`, 768
MB/CPU otherwise. The two faults want opposite things — the disk fault starves the consumer of
*disk*, the memory fault starves it of *memory*, and LTTng's buffers **are** memory. Buffer size
affects only whether an event was dropped, never what a kept event contains.

### The Train Ticket load CSV gap

**103 of 134 Train Ticket runs have no client-side request CSV.** Sock Shop has all 169. The
kernel trace, spans, container logs and Prometheus export are complete in every one of the 303
runs — only the load generator's own record is affected.

Which runs kept theirs is not random. It is exactly the families whose fault does **not** block a
request:

| kept the CSV | lost it |
|---|---|
| `normal` 10/10, `anomaly_cpu` 5/5, `anomaly_disk` 5/5 | every other family, 0 or 1 of each |

The cause, read off the empty `_load.log` files (no error, no completion line — the process was
killed mid-flight): Train Ticket's `load_generator.py` wrote the CSV only after
`with ThreadPoolExecutor(...) as ex:` exited, and that block waits for every worker with no
timeout. A worker checks the clock only *between* journeys, and a journey is ~5 sequential
requests at a 30 s timeout — so under a fault that blocks requests a worker overshoots the run by
up to ~150 s. `run_scenario.sh`'s cleanup trap killed the generator long before that, with every
row still in memory. Sock Shop's generator bounds its join at 15 s and always writes, which is
why it lost nothing.

**Fixed 6 Sept** in `train-ticket-collection-scripts/load_generator.py`: the write is now a
shared function reachable from three paths — normal completion, a bounded `duration + 20 s`
deadline, and a `SIGTERM` handler. Verified against a host that accepts and never answers: the
CSV lands at the deadline and the process exits immediately instead of hanging for the request
timeout.

**The lost CSVs are not recoverable** — the rows only ever existed in the killed process's
memory. Re-collecting 103 Train Ticket runs costs roughly 620 GB and a day of VM time, for one
modality of four. Whether that is worth it depends on whether the ablation study needs a
client-side view on Train Ticket; it is a research call, not a defect to quietly patch.

**The 10 outstanding Train Ticket verdicts are resolved** (16 Sept, CAMPAIGN-ISSUES 23).
`slow_db` is `no_metric_signature` - measured, not assumed. `svc_net` is the one family that
genuinely needs re-collecting: 4 of its 5 runs produced 0% packet loss, so the injection did not
take and no target can rescue it.

---

## The re-collection, 15-16 September

53 Sock Shop runs were retired and 54 collected in their place, on a purpose-built VM
(`stratatrace-ss`, same `n2-custom-12-40960` shape as the original so `thief_share` and
`anomaly_mem` still divide correctly).

| family | runs | why it was re-collected | outcome |
|---|---|---|---|
| 5 x `code_*` | 26 | contaminated baseline: the recipe restarted the container **inside** the baseline window, so baseline TCP retransmission read 34.7-79.9% | fixed; `arm` restarts before tracing, `inject` writes a flag |
| `anomaly_net` | 8 | 3 of 8 applied netem **before** the incident stamp | fixed; **baseline median retransmission 0%** |
| `dns_delay` | 5 | r4's injection never took (EMFILE exactly 0) | all 5 consistent |
| `lock_contention` | 5 | 3 of 5 `unconfirmed` | 2/5 -> **5/5 confirmed** |
| `deadlock` | 5 | 1 of 5 `unconfirmed` | 4/5 -> **5/5 confirmed** |
| `fd_exhaustion` | 5 | 3 of 5 `unconfirmed` | the *target* was wrong, not the runs (issue 22) |

The retired copies are at `superseded-20260917/` - **moved, never deleted**, because they are the
evidence for issues 17 and 21 and for the before/after comparison. `WHY.md` there records the
reason per family. Three of the ten retired families were not contaminated at all
(`fd_exhaustion`, `lock_contention`, `deadlock`); they were retired because a verified
replacement exists and leaving both invites mixing.

**Do not mix the two sets.** Everything under `v2/sockshop-recollected-20260915/` supersedes the
same-named family in `superseded-20260917/`.

## Where the data is

| | location |
|---|---|
| archives, original | Trillium `/scratch/yuvraj17/stratatrace/v2/{sockshop,trainticket}/` |
| archives, re-collected | Trillium `/scratch/yuvraj17/stratatrace/v2/sockshop-recollected-20260915/` - 12 archives, 156.4 GB, **all verified** |
| retired | Trillium `/scratch/yuvraj17/stratatrace/superseded-20260917/` - 105 GB archives + 783 GB extracted + 53 stale packs |
| working copy | Trillium `/scratch/yuvraj17/stratatrace/data/stratatrace-v2/<app>/<recipe>/<run_id>/` - extracted, fully decompressed |
| Prometheus TSDBs | originals `C:\workplace\stratatrace-v2-prometheus\`; the re-collection's is on Trillium in `provenance_20260916.tar.gz` |
| campaign logs | originals `C:\workplace\stratatrace-v2-campaign-logs\`; the re-collection's is in `provenance_20260916.tar.gz` |

**Every collection VM has been deleted.** The original pair went on 2026-09-07; the replacement
`stratatrace-ss` and both its disks went on 2026-09-16 once its work was verified. GCP cost for
this project is zero. **Trillium holds the only copy of the dataset.**

Before the replacement VM was deleted, three things that existed *only* on it were swept off -
they were not in any run bundle, because the transfer key was deliberately scoped to recipe
directories:

- the Prometheus TSDB (179 MB) - the continuous record the per-run exports cannot reconstruct,
  and what a corrected verification target gets re-scored against
- the `gate01` validation run (1.4 GB) - proof that machine was set up correctly
- `fault-state/` (54 dirs), the bootstrap and gate logs, and `docker save` of the five images
  built there (`frontend-bugs:v2`, `catalogue-bugs:v2`, the two OTel images, the workload image)

They are `provenance_20260916.tar.gz` and `provenance_vm_20260917.tar.gz`.

**Transfers now pull, they do not push.** Alliance requires MFA as a second factor even when a
CCDB-registered key passes as the first, so a batch-mode push from a VM cannot authenticate.
Trillium can dial out to a GCP VM, so `transfer/pull_from_vm.sh` inverts the direction. The key
it uses lives on a shared login node, so it is bound to a forced command that can only list
recipes or stream one. See `transfer/README.md`.

**Verify archives with a job array, not a loop.** `transfer/verify_archives_array.sbatch` gives
each archive its own node: 120 MB/s each, the whole set in about three minutes. Three earlier
single-node attempts were killed at their wall clocks - the work is bound by how fast one node
pulls gzip off `/scratch`, so four archives on one node just split one pipe four ways.

### Prometheus snapshots

The full series database from each VM, taken 6 Sept after collection finished, **with Prometheus
stopped** so the TSDB is consistent rather than mid-write.

| | on the VM | local copy | TSDB | verified |
|---|---|---|---|---|
| Sock Shop | `/mnt/archive/prometheus/` | `C:\workplace\stratatrace-v2-prometheus\sockshop-prometheus.tar` | 362 MB | sha256 OK |
| Train Ticket | `/mnt/archive/prometheus/` | `C:\workplace\stratatrace-v2-prometheus\trainticket-prometheus.tar` | 582 MB | sha256 OK |

Each archive holds `tsdb.tar.gz`, the `prometheus.yml` it was scraped with, `SHA256SUMS`, and a
README with the restore command:

```bash
tar xf tsdb.tar.gz
docker run --rm -p 9090:9090 -v $PWD/tsdb:/prometheus   -v $PWD/prometheus.yml:/etc/prometheus/prometheus.yml   prom/prometheus --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus
```

**Why, when every bundle already has its own metrics export.** The per-run exports cover each
run's own window and were never at risk. The snapshot preserves the *continuous* record — the
gaps between runs, cross-run baselines, and any question of the whole campaign nobody has
thought of yet. Retention was the 15-day default, so this would have aged out regardless of what
happened to the VMs.

It also means the 10 outstanding Train Ticket verdicts can be calibrated later without the VMs
existing.

### Campaign logs

Swept off both VMs on 6 Sept before deleting them, because they were the one thing that existed
*only* there — the run bundles carry container logs, `meta/`, ground truth and verdicts, but not
the driver's own narrative.

| | local copy |
|---|---|
| Sock Shop | `C:\workplace\stratatrace-v2-campaign-logs\sockshop-campaign-logs.tar.gz` (259 MB) |
| Train Ticket | `C:\workplace\stratatrace-v2-campaign-logs\trainticket-campaign-logs.tar.gz` (0.4 MB) |

Holds `campaign_*.out` (every run announced with its verdict, in order, plus the `[matrix] SKIP`
lines saying which families were deliberately not run on Train Ticket), the per-run driver log for
all 303 runs, and the recipes' `fault-state/` directory. Both sha256-verified after transfer.

Sock Shop's is 100x larger for a dull reason: the OTel Java agent's `logging` exporter writes every
span to stdout and the driver captured it, so 16 runs have ~140 MB logs (one is 659,118 lines).
That content is redundant with each bundle's `otlp/spans.jsonl`; it compresses ~9x and was not
worth separating.

### The working copy

Extracted and decompressed 7 September 2026, so everything is directly readable — no decode cache,
no `.gz` anywhere.

    /scratch/yuvraj17/stratatrace/data/stratatrace-v2/<app>/<recipe>/<run_id>/

| | |
|---|---|
| runs | **303** (169 sockshop + 134 trainticket) |
| files | 831,475 |
| size | **7.3 TB** (from 778 GB of archives) |
| `.gz` remaining | **0** |

Verified by opening a trace with babeltrace 2.1.2 rather than by counting files:

    [04:12:53.521030424] ... net_dev_queue: { cpu_id = 2 }, { pid = 18364, procname = "conn62" ...
    [04:12:53.521030652] (+0.000000228) ... power_cpu_idle: { cpu_id = 0 }, ...

**Decompressing was not just the kernel traces.** 145,981 of the ~150,000 `.gz` files were the
per-run Prometheus export — roughly 440 metric series per run, each its own gzipped JSON. Only
~4,000 were kernel `channelN_N.gz`. Doing "the traces" alone would have left 97% of them in place.

The apps stay in separate trees because both use the same recipe names; merging them would put
Sock Shop's `anomaly_cpu` and Train Ticket's in one directory. Run ids differ (`tt_` prefix), so
nothing would be lost, but "how many `anomaly_cpu` runs are there" would stop having one answer.

Reproduce with `transfer/extract_v2_job.sbatch` then `transfer/decompress_v2_job.sbatch`
(chain the second with `--dependency=afterok:<jobid>`). Both are resumable and took 19 and 16
minutes on one 192-core node.

### Bundle layout

```
<run_id>/
  kernel/kernel/       CTF trace, channel0_* gzipped (pigz), metadata+index plain
  otlp/spans.jsonl     OTLP spans, sliced to this run by byte offset
  logs/                per-container docker logs for the run window
  ust/                 LTTng-UST relay stream (cross-layer clock bridge)
  meta/                runinfo_start/end (clock anchors), lttng_enabled_kernel.txt,
                       event_loss.json
  ground_truth.json    what was injected, when, with which parameters
  verification.json    current verdict
  verification.as-collected.json   the verdict at collection time, where re-scored
  verification.png     metric plot over the injection window
  MANIFEST.json        checksums, sizes, usable/not verdict
```

## On Trillium

**Transferred and verified 6 September 2026.** Both applications now live at
`/scratch/yuvraj17/stratatrace/v2/{sockshop,trainticket}/`, kept apart from v1 because the two
releases share every recipe name.

| | recipes | runs source → Trillium | mismatches | size |
|---|---|---|---|---|
| Sock Shop | 28 / 28 | 169 → **169** | 0 | 464 GB |
| Train Ticket | 21 / 21 | 134 → **134** | 0 | 315 GB |

1.18 TB of bundles compressed to **779 GB** in **51 files** — one `tar.gz` per recipe plus a
Prometheus snapshot each. The file count matters as much as the bytes: SciNet quotas inodes, and
831,416 source files arriving as 51 archives moved `/scratch` from 967K files to ~1.0M against a
10M limit. Space after the push: 4.8 TB of 25 TB.

Verification is not a checksum of the stream — it decompresses every archive on the far side and
counts `meta/runinfo_end.txt` entries against the source, so a silently truncated archive cannot
pass. It runs `nice -n 19 ionice -c3`, because 779 GB of decompression on a shared login node is
otherwise antisocial.

`/scratch` retention is confirmed safe for at least a year, so there is no need to chase
`/project` quota — which could not have held v2 anyway (~705 GB free against a 1024 GB quota).

### What it took to get there

The layout on the VMs was uniform and nothing was left unarchived:

| check | Sock Shop | Train Ticket |
|---|---|---|
| runs under `/mnt/archive/runs/<recipe>/<run_id>/` | 169 | 134 |
| packaged (`MANIFEST.json` + `SHA256SUMS`) | 169 | 134 |
| still sitting in `~/traces` | 0 | 0 |
| CTF streams gzipped (`.idx` left plain, as required) | yes | yes |
| aux `_metrics/` + `_load.*` beside each bundle | yes | yes |
| archive disk | 692 GB used / 293 GB free | 497 GB used / 487 GB free |

`transfer/push_to_trillium.sh` needed four fixes before it would work against this layout — the
archive move was added mid-campaign and the script still assumed v1's:

1. **`DEST_ROOT` no longer has a default.** It used to default to
   `/scratch/yuvraj17/stratatrace/repo`, which is where v1 lives. v2 uses the same recipe names,
   so the default would have overwritten v1's tarballs silently. It is now required.
2. **`--verify` counted directories, not runs.** Each recipe dir now also holds a
   `<run_id>_metrics/` per run, so `ls -d */` returned exactly twice the run count and every
   recipe reported `MISMATCH`. It now counts `meta/runinfo_end.txt`.
3. **The Prometheus snapshot was not being shipped.** It lives at `/mnt/archive/prometheus`,
   outside `SRC`, so nothing carried it. It now goes as `_prometheus_snapshot.tar.gz`.
4. **`--setup-master` required a destination it never uses.** Fix 1 put the `DEST_ROOT` guard with
   the top-of-file settings, so it fired before the `--setup-master` branch — making the one
   command you must run *first* fail on the one variable it does not need.

**Auth, measured rather than assumed.** Registering the VM keys in CCDB is necessary but not
sufficient: `ssh -vv` reports `Server accepts key … Authenticated using "publickey" with partial
success`, then Trillium demands `keyboard-interactive` MFA anyway. No key-only route exists — five
candidate data-transfer hostnames are all NXDOMAIN. Hence the ControlMaster design: one human MFA
per VM, and every push stream reuses that master.

The per-run aux files need no separate archive any more — they sit inside `SRC/<recipe>/`, so the
per-recipe tarball already carries them.

```bash
# once per VM, interactively - the only step a human must do (MFA)
bash transfer/push_to_trillium.sh --setup-master

# then, per application
DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=sockshop   bash transfer/push_to_trillium.sh
DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=trainticket   bash transfer/push_to_trillium.sh

DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=sockshop   bash transfer/push_to_trillium.sh --verify
```

Measured throughput: ~125 MB/s combined across both VMs, the whole 1.18 TB in about 75 minutes.
The push is atomic (`.partial` → `mv`) and resumable — it skips archives that already exist, so an
interruption costs only the archive in flight.

## Reproducing the numbers here

On either VM:

```bash
# full per-run index
python3 ~/microservice-trace-dataset/microservice-lttng-data-collection-scripts/rebuild_manifest.py

# what is still outstanding, grouped by what it would cost to fix
python3 ~/microservice-trace-dataset/microservice-lttng-data-collection-scripts/campaign_issues.py

# re-derive verdicts with the current targets (needs Prometheus, or an offline adapter later)
bash ~/microservice-trace-dataset/microservice-lttng-data-collection-scripts/rescore_runs.sh
```
