# 5 September 2026 — the v2 campaign starts, and what the first 50 runs taught

Both campaigns launched: **Sock Shop 169 runs, Train Ticket 134**. Every run so far is clean.

## Caught before launch (pre-flight)

- **The Train Ticket driver had never been runnable.** `source "$SD/..."` where the script
  defines `TTD` — under `set -u` it dies on the first statement that matters. Half the campaign
  would have collected nothing. A `--dry-run` found it in four seconds.
- **Nothing moved finished runs off the collection disk.** Train Ticket would have filled its
  root at ~run 21, Sock Shop at ~78, with both 1 TB archives empty.
- **The Train Ticket driver never packaged anything** — no manifest, checksums, verdict, or
  event-loss record. Its half of the dataset would have been quietly poorer than Sock Shop's.

## Caught during the campaign

### Train Ticket discarded 27 million events per run

`LOSSY:27132559`, `LOSSY:28640833`. Sock Shop was clean throughout.

The arithmetic looked fine, which is the point. Train Ticket produces ~193–211 MB/s of trace
and the disk sustains 206 MB/s — a ~5 MB/s deficit, about 1.2 GB across a run, comfortably
inside the **4 GB total** buffer. But buffers are **per CPU**, and 40 JVMs do not spread evenly:
one hot CPU exhausted its 256 MB while fifteen sat idle. **The total was never the constraint.**

Verified at 768 MB/CPU: discarded 0, lost packets 0. Sock Shop keeps 256 MB/CPU (clean at
53 MB/s, and only 40 GB of RAM).

The obvious fix — a faster disk — was unavailable: SSD quota sits at 400 GB of a 500 GB limit.
Measuring first meant the free fix turned out to be the right one.

*This is exactly what v2's event-loss recording was added for. In v1 both runs would have
entered the dataset indistinguishable from clean ones.*

### Container logs reached 79 GB

More than half Train Ticket's root disk, against 8.9 GB of images. Docker's json-file driver is
unbounded, and 40 JVMs each dual-export spans to stdout for the UST clock bridge. That traffic
must exist during a run; it need not survive one, and each run's logs are already captured into
its bundle.

Truncated between runs: **79 GB → 4.6 GB**. My per-run disk arithmetic had been correct — the
runs were never what was filling the disk.

## The verification targets were the real story

**20 of 22 canonical targets had never been checked against a real run.** Only the ten
calibrated on 4 Sept carried measured evidence. Four distinct failure modes appeared:

| family | what was wrong | evidence |
|---|---|---|
| `anomaly_disk` | target was a **bounded** metric our own tracing had already consumed | io_time 0.95x, but writes/s **3.56x**, bytes **2.50x**, queue depth **2.36x** |
| `anomaly_mem` | demanded a floor the fault cannot reach; comment said *"Finalize on VM calibration"* | needed <0.25, measured floor **0.40**, sigma −14.6 |
| `anomaly_cpu` (TT) | sigma gate **mathematically impossible** | 5σ demands **124.9% CPU** |
| `dependency_outage` | sigma gate **mathematically impossible** | −2σ demands **−0.0008 cores** |

### The one that mattered most was a false positive, and it never ran

Train Ticket idles at **0.4141 MemAvailable** — 40 JVMs, MySQL and Nacos hold ~35 GB of 62 GB.
The Sock Shop-calibrated threshold of 0.60 is *already satisfied at rest*, so `anomaly_mem`
would have reported **`confirmed` on all five runs whether or not anything was injected.**

A false negative costs a re-score; the data is intact and the verdict recoverable. A false
positive **certifies a fault that never happened**, and downstream nothing distinguishes it from
a real one. Caught by checking baselines before the family ran, rather than reading verdicts
after.

### Two lessons worth carrying

**An observability dataset's own collection consumes the resources its faults target.** LTTng
writes 53 MB/s continuously on Sock Shop — precisely the measured baseline of
`node_disk_written_bytes_total`. Any *bounded* metric of a contended resource is blind by
construction. Unbounded counters are not.

**A threshold calibrated on one machine is a guess on another**, and the dangerous direction is
when the new machine's baseline already satisfies it. Sigma is delta ÷ baseline noise, so a
noisy baseline silently raises the bar past the metric's own range — which is why `anomaly_cpu`
is confirmed 5/5 on one application and borderline on the other for the *same* injection.

`verify_injection` now records `sigma_required_value`, so an impossible gate is visible in the
bundle rather than spread across three fields.

## What is recoverable

13 runs carry wrong verdicts. **All are good data** — faults fired, ground truth correct, traces
clean. Each bundle ships its own metrics export (**440 metric files**, all the series the
corrected targets need), so verdicts are re-derivable offline, permanently, without the VMs.

**Nothing needs re-collecting.**

## Process notes

- The campaign drivers **cannot** be edited while running: bash reads scripts incrementally.
  Deploy with `git checkout origin/<branch> -- <one file>`, never `git pull`. Per-run scripts
  (`campaign_finish_run.sh`, `verify_injection.py`, the targets files) are safe — they are
  invoked fresh each run.
- My own bug worth naming: a patch asserted on most replacements but not one, so `.replace()`
  matched nothing and said nothing. **Every edit to a file you cannot immediately re-read needs
  an assert.**

---

## The disk fault degrades the trace collector — on one application only

`tt_anomaly_disk_aggressive_steady_r4` came back **`LOSSY:2481855`** while verifying
`confirmed`. One of four repeats; ~0.25% of the run's events.

This is the predicted consequence of the numbers measured earlier the same day. On Train Ticket
LTTng writes **~176 MB/s** to a disk that sustains **206 MB/s**. `anomaly_disk` adds `stress-ng`
`direct,fsync` writes on top, and the consumer falls behind. Sock Shop, tracing at 53 MB/s, has
four times the headroom and shows no loss on the same family.

**The fault and the instrument contend for the same device.** That is not a bug to fix so much
as a property to state: on a sufficiently busy application, a disk-saturation fault and a
disk-backed tracer cannot both be at full strength.

Deliberately NOT "fixed" by:

- **Bigger buffers** — currently 768 MB/CPU (12 GB of 62). Going to 1 GB/CPU leaves ~10 GB
  against 40 JVMs, and LTTng allocates at session start, so a failed allocation is a failed run.
  More buffer also only *delays* a sustained overrun rather than removing it.
- **A weaker fault on Train Ticket** — that would make `anomaly_disk` a different experiment on
  the two applications, which is precisely what the two-application design exists to avoid.

Recorded instead. Loss is captured per run in `meta/event_loss.json` and surfaced in the
manifest, so analysis can exclude or weight these runs explicitly. Watching whether r5 repeats
it before considering a modest buffer increase.

Related, and the same root cause seen from the other side: the disk fault adds only **+24 MB/s**
on Train Ticket against **+80 MB/s** on Sock Shop, because there is barely 30 MB/s of headroom
left after tracing. The instrument does not merely fail to *see* the fault — it limits how large
the fault can be.
