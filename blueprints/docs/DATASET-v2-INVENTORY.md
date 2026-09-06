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

Every run carries: kernel CTF trace, OTLP spans, container logs, meta/clock anchors, plus a
per-run Prometheus export (~440 metric series) and the load generator's request CSV alongside
the bundle.

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
  Sock Shop's services expose a latency histogram while Train Ticket's do not. The fault is
  still observable in the load-generator CSV and the kernel trace.

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
