# StrataTrace v2 — what was collected

**Collection finished 6 September 2026.** 303 runs across two applications, four modalities each.

This is the inventory: what exists, how good it is, and what to be careful about. Every number
here was read off the bundles with
`microservice-lttng-data-collection-scripts/rebuild_manifest.py`, not from the campaign
drivers' own manifests (which are unreliable for this campaign — see
[CAMPAIGN-ISSUES.md](../../CAMPAIGN-ISSUES.md) issue 7).

---

## Headline

| | Sock Shop | Train Ticket | total |
|---|---|---|---|
| runs | **169** | **134** | **303** |
| packed size | 688 GB | 493 GB | **1.18 TB** |
| runs with all 4 modality dirs | 169 / 169 | 134 / 134 | **303 / 303** |
| **kernel traces without event loss** | **169 / 169** | **133 / 134** | **302 / 303** |

The single lossy run is `tt_anomaly_disk_aggressive_steady_r4` (2,481,855 discarded, ~0.25% of
that run). It is kept deliberately — see [caveats](#caveats-that-affect-analysis).

Every run carries: kernel CTF trace, OTLP spans, container logs, meta/clock anchors, and a
per-run Prometheus export (~440 metric series) alongside the bundle.

The client-side request CSV is **complete on Sock Shop (169/169) and partial on Train Ticket
(31/134)** — see [the load CSV gap](#the-train-ticket-load-csv-gap). The four trace modalities
are unaffected.

## Verification verdicts

Of 283 fault runs (303 minus 20 fault-free `normal` reference runs):

| verdict | Sock Shop | Train Ticket | meaning |
|---|---|---|---|
| `confirmed` | 135 | 91 | the fault moved its pre-registered target metric |
| `borderline` | 12 | 4 | right direction and coverage, magnitude below threshold |
| `unconfirmed` | 7 | 25 | target did not move — **see caveats, mostly uncalibrated targets** |
| `no_metric_signature` | 5 | 4 | **measured** to have no metrics signature; this is a finding |
| `n/a` (normal runs) | 10 | 10 | nothing injected, nothing to verify |

**A verdict is QC metadata, not data.** Every run above contains a real injection with correct
ground truth; `unconfirmed` means the *metric check* failed, not that the fault did not happen.
Verdicts are re-derivable at any time — the original as-collected verdict is preserved in each
bundle as `verification.as-collected.json`.

## Per-family counts

Both applications, identical unless noted. 5 repeats per family at `aggressive`/`steady`; the
intensity and workload studies add 3 more to selected families (hence 8s and 11s).

| family | SS | TT | notes |
|---|---|---|---|
| `normal` | 10 | 10 | fault-free reference (5 steady + 5 burst) |
| `anomaly_cpu` | 5 | 5 | |
| `anomaly_disk` | 5 | 5 | **not the same experiment on both** — see caveats |
| `anomaly_mem` | 8 | 8 | |
| `anomaly_net` | 8 | 8 | TT: 4 `no_metric_signature` by design |
| `dependency_outage` | 5 | 5 | |
| `error_storm` | 8 | 8 | |
| `noisy_neighbor` | 8 | 8 | |
| `queue_backlog` | 5 | — | TT has no message broker |
| `slow_db` | 11 | 11 | TT verdicts outstanding |
| `svc_cpu_cap` | 8 | 8 | **ineffective on TT** — see caveats |
| `svc_mem_cap` | 8 | 8 | |
| `svc_net` | 5 | 5 | TT verdicts outstanding |
| `lock_contention` | 5 | 5 | new in v2 |
| `priority_inversion` | 5 | 5 | new in v2 |
| `deadlock` | 5 | 5 | new in v2 |
| `fd_exhaustion` | 5 | 5 | new in v2 |
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

**The five code defects share one metrics signature.** All produce catalogue throughput
collapsing to 0.33–0.47x; none is distinguishable from the others, or from the container restart
that applying it requires, in the metrics modality alone. Latency is *not* a discriminator — p95
goes **down**, because the surviving requests are the fast ones. Discrimination has to come from
the kernel and trace modalities, which is what the ablation study is for.

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

**10 Train Ticket verdicts are outstanding** (`slow_db` ×5, `svc_net` ×5). Their data is intact.
`svc_net`'s candidate metrics rise *uniformly* ~2.1x across unrelated services, which reads as
load drift rather than a targeted fault; registering it without separating fault from drift
would risk certifying noise.

## Where the data is

| | location |
|---|---|
| Sock Shop | `stratatrace-ss:/mnt/archive/runs/<family>/<run_id>/` |
| Train Ticket | `stratatrace-tt:/mnt/archive/runs/<family>/<run_id>/` |

GCP project `teleeporter`, zone `us-east1-d`. Each run directory also has sibling
`<run_id>_metrics/` and `<run_id>_load.csv` — the transfer layer packages those into
`_aux_metrics_load.tar.gz` (see `transfer/`).

**Not yet transferred to Trillium.** At 1.18 TB the two halves fit their own 1 TB archives but
not a single one; plan the move per application.

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

## Moving it to Trillium

Checked 6 Sept on both VMs. The layout is uniform and nothing is left unarchived:

| check | Sock Shop | Train Ticket |
|---|---|---|
| runs under `/mnt/archive/runs/<recipe>/<run_id>/` | 169 | 134 |
| packaged (`MANIFEST.json` + `SHA256SUMS`) | 169 | 134 |
| still sitting in `~/traces` | 0 | 0 |
| CTF streams gzipped (`.idx` left plain, as required) | yes | yes |
| aux `_metrics/` + `_load.*` beside each bundle | yes | yes |
| archive disk | 692 GB used / 293 GB free | 497 GB used / 487 GB free |

`transfer/push_to_trillium.sh` needed three fixes before it would work against this layout — the
archive move was added mid-campaign and the script still assumed v1's:

1. **`DEST_ROOT` no longer has a default.** It used to default to
   `/scratch/yuvraj17/stratatrace/repo`, which is where v1 lives. v2 uses the same recipe names,
   so the default would have overwritten v1's tarballs silently. It is now required.
2. **`--verify` counted directories, not runs.** Each recipe dir now also holds a
   `<run_id>_metrics/` per run, so `ls -d */` returned exactly twice the run count and every
   recipe reported `MISMATCH`. It now counts `meta/runinfo_end.txt`.
3. **The Prometheus snapshot was not being shipped.** It lives at `/mnt/archive/prometheus`,
   outside `SRC`, so nothing carried it. It now goes as `_prometheus_snapshot.tar.gz`.

The per-run aux files need no separate archive any more — they sit inside `SRC/<recipe>/`, so the
per-recipe tarball already carries them.

```bash
# once, interactively (does the MFA)
bash transfer/push_to_trillium.sh --setup-master

# then, per application
DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=sockshop   bash transfer/push_to_trillium.sh
DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=trainticket   bash transfer/push_to_trillium.sh

DEST_ROOT=/scratch/yuvraj17/stratatrace/v2 SRC=/mnt/archive/runs APP=sockshop   bash transfer/push_to_trillium.sh --verify
```

**Open before pushing:** 1.18 TB has to fit the `/scratch` quota alongside v1, and the two halves
were sized against 1 TB archives individually, never together. Confirm free space and inode
budget on Trillium first — the push is resumable (it skips archives that already exist), so a
quota stop is recoverable, but it is cheaper to check.

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
