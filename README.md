# SockShop Microservice Trace Dataset (Kernel + UST + Container Metadata)

A reproducible observability dataset collected from the Weaveworks **Sock Shop**
microservice benchmark running on a single Linux VM. Each run produces a
time-aligned bundle of:

- raw **LTTng kernel** traces (full kernel event capture in CTF format),
- raw **LTTng userspace (UST)** traces relaying OpenTelemetry span events from
  selected Sock Shop services,
- periodic **container and process metadata** snapshots (Docker inspect, process
  tables, cgroup/namespace information).

The dataset is intended for research on system observability, distributed
tracing, anomaly detection, root-cause analysis, microservice performance
modeling, and cross-layer telemetry fusion.

---

## At a glance

| Property | Value |
|---|---|
| Application | Weaveworks Sock Shop (Apache-2.0) |
| Deployment | Docker Compose on a single Linux VM (Ubuntu 24.04, kernel 6.8.0-1052-gcp, 12 vCPU) |
| Tracing tools | LTTng 2.15 (kernel + python UST), Babeltrace2 |
| Scenarios | 5 (`normal`, `anomaly_cpu`, `anomaly_disk`, `anomaly_mem`, `anomaly_net`) |
| Runs per scenario | 5 (`run01`–`run05`) |
| Total runs | 25 |
| Run duration | 100 s of measured load per run |
| Total size (raw) | ~148 GB |
| Per run, kernel | ~8 GB (CTF, full kernel event capture) |
| Per run, UST | ~60 MB (CTF, OTel span events) |
| Per run, meta | ~6–7 MB (text + JSON snapshots) |

---

## Top-level directory layout

The dataset ships inside this repository under two sibling directories:

```
<repo_root>/
├── traces/                        # raw LTTng kernel+UST captures and per-run meta
│   ├── metadata.csv               # run-level index (see "Run-level metadata.csv" below)
│   ├── normal/
│   │   ├── run01/
│   │   ├── run02/
│   │   ├── run03/
│   │   ├── run04/
│   │   └── run05/
│   ├── anomaly_cpu/    run01 ... run05
│   ├── anomaly_disk/   run01 ... run05
│   ├── anomaly_mem/    run01 ... run05
│   └── anomaly_net/    run01 ... run05
└── pdf_proofs_of_injection/       # Grafana dashboard exports per run (see "Grafana proof PDFs" below)
```

### Per-run layout

Every `<scenario>/<run>/` directory contains three sibling subdirectories
written by the collection pipeline:

```
<scenario>/<run>/
├── kernel/                        # LTTng kernel session output (CTF)
│   └── kernel/
│       ├── metadata                # CTF metadata
│       ├── index/                  # CTF index files (*.idx)
│       └── channel0_0 ... channel0_11   # per-CPU CTF stream files
├── ust/                           # LTTng python-domain UST session output (CTF)
│   └── ust/uid/1002/64-bit/
│       ├── metadata
│       ├── index/lttng_python_channel_*.idx
│       └── lttng_python_channel_0 ... lttng_python_channel_11
└── meta/                          # container and process snapshots (~70+ files)
    ├── runinfo_{start,end}.txt
    ├── docker_ps_{start,end,tick_<UTC>}.txt
    ├── container_list_{start,end,tick_<UTC>}.txt
    ├── ps_threads_{start,end,tick_<UTC>}.txt
    ├── inspect_<container>_{start,end,tick_<UTC>}.json
    ├── top_<container>_{start,end,tick_<UTC>}.txt
    └── proc_<container>_{start,end,tick_<UTC>}.txt
```

---

## What each part contains

### Kernel traces (`<run>/kernel/kernel/`)

Captured with `lttng enable-event -k --all '*'` and the contexts
`--type=pid --type=tid --type=procname`. Includes:

- syscall entry/exit events (`syscall_entry_*`, `syscall_exit_*`),
- scheduler events (`sched_switch`, `sched_wakeup`, `sched_stat_runtime`, ...),
- timer events (`timer_hrtimer_*`),
- block I/O, network device, RCU, power, and other kernel tracepoints,
- per-event context fields: `pid`, `tid`, `procname`, plus event-native fields
  such as `ret` on syscall exits, `cpu_id`, etc.

There are 12 per-CPU CTF channel files (one per vCPU on the 12-core host) plus
the CTF `metadata` file and an `index/` directory.

Read with Babeltrace2:

```bash
babeltrace2 --output-format=text <run>/kernel/kernel
```

Sample line:

```
[00:42:51.993135361] (+0.000000340) lttng-traces-microservice syscall_exit_futex:
  { cpu_id = 11 },
  { pid = 78339, tid = 78339, procname = "python3" },
  { ret = 0, uaddr = 108935974470848, uaddr2 = 0 }
```

### Userspace traces (`<run>/ust/ust/uid/1002/64-bit/`)

UST events from the `lttng_python` domain. They are produced by a host-side
relay (`microservice-lttng-data-collection-scripts/agents/otel-to-lttng.py`)
that subscribes to `docker logs -f --timestamps` on selected Sock Shop service
containers, parses each Spring Boot `LoggingSpanExporter` line, and re-emits the
span as a Python `logging` record into the LTTng Python session.

Relayed services: `carts`, `orders`, `shipping`, `queue-master`.

Each UST event carries:

- the original Spring Boot span string (operation name, span kind),
- `trace_id` and `span_id` (hex),
- service and container name,
- the Docker-reported timestamp of the span line (`docker_ts`),
- the relay's wall-clock timestamp at the moment it forwarded the line
  (`relay_ts_ns`),
- the standard LTTng `vpid`, `vtid`, `procname`, `cpu_id` contexts.

Sample line:

```
[00:42:59.336311000] (+?.?????????) lttng-traces-microservice lttng_python:event:
  { cpu_id = 6 },
  { vpid = 79158, vtid = 79158, procname = "python3" },
  { asctime = "2026-03-24 04:42:59,335",
    msg = "service=carts container=docker-compose_carts_1 phase=export
           docker_ts=2026-03-24T04:42:59.335401499Z
           relay_ts_ns=1774327379335924919
           trace_id=6424612383807cd1189c15a8d3236908
           span_id=2500aa8dabb2415e
           kind=CLIENT op=\"find data.cart\"",
    logger_name = "otel.spans", funcName = "<module>", lineno = 86,
    int_loglevel = 20, thread = 712822784, threadName = "MainThread" }
```

UST events are *export-time log records*, not native span boundary events,
so they should be treated as a record of when each span was reported, not as a
clean start/stop pair. Trace and span IDs are still usable for cross-layer
correlation with the kernel trace.

### Meta snapshots (`<run>/meta/`)

Periodic state of the running stack, written at three kinds of moments:

- `*_start.*` — once, at the beginning of the run, just after LTTng sessions
  are started,
- `*_tick_<UTC>.*` — repeatedly every 10 s while the run is in progress,
- `*_end.*` — once, after load generation finishes and just before LTTng
  sessions are torn down.

Snapshot file types (one of each per timestamp tag):

| File | Source | Purpose |
|---|---|---|
| `runinfo_<tag>.txt` | shell | UTC timestamp, hostname, kernel release, scenario, run id, configured duration |
| `docker_ps_<tag>.txt` | `docker ps` | container name, image, status |
| `container_list_<tag>.txt` | filtered `docker ps` | exact list of Sock Shop containers used by the run |
| `ps_threads_<tag>.txt` | `ps -eLo` | system-wide per-thread snapshot (pid, tid, ppid, cpu, sched class, state, comm, cmd) |
| `inspect_<container>_<tag>.json` | `docker inspect` | full container inspect JSON (image, mounts, networks, host config) |
| `top_<container>_<tag>.txt` | `docker top` | per-container thread list with host-side pid, tid, cpu, state, comm, args |
| `proc_<container>_<tag>.txt` | `/proc/<pid>/cgroup` + `/proc/<pid>/ns` | the container's host pid, its cgroup hierarchy, and its namespace symlinks |

These snapshots let downstream analysis map kernel `pid/tid/procname` back to
containers and services without depending on later container state.

### Run-level `metadata.csv`

`traces/metadata.csv` is a header-less append-log written by the collection
script after each run. Columns:

```
scenario, run_id, start_time_utc, duration, profile
```

Example:

```
normal,run01,Fri Mar 27 02:55:10 UTC 2026,100s,FULL
anomaly_cpu,run02,Fri Mar 27 03:56:34 UTC 2026,100s,FULL
```

Note: some `(scenario, run_id)` pairs appear more than once because earlier
collection attempts were retried and the on-disk run directory was overwritten
by a later attempt. The CSV preserves the full collection history; the
*content* of `<scenario>/<run>/` corresponds to the **most recent** entry for
that pair. The wall-clock timestamps inside `meta/runinfo_start.txt` are the
ground truth for when the surviving run was actually collected.

---

## Grafana proof PDFs (`pdf_proofs_of_injection/`)

Alongside the raw traces, the dataset includes Grafana dashboard exports
captured *while each run was executing*. They are intended as independent,
visually-inspectable evidence that the application was actually under load
during the normal runs and that the injected fault actually moved the
per-service signals during the anomaly runs.

All exports come from the Grafana "Sock Shop Performance" dashboard, which
shows, per Sock Shop service (`catalogue`, `carts`, `orders`, `payment`,
`shipping`), two side-by-side panels:

- **QPS** (requests per second, broken out by HTTP status class such as `2xx`),
- **Latency** (50th / 95th / 99th quantile and mean).

The host-level metrics (CPU, memory, disk, network) are visible on the
companion "VM / Node" view that is captured as the `*B.pdf` page of each pair.

### File inventory

| File | Scenario | What it shows |
|---|---|---|
| `normal01.pdf` ... `normal05.pdf` | `normal/run01` ... `normal/run05` | Per-service QPS and latency during one normal run. One page per run. |
| `cpu-stress01A.pdf`, `cpu-stress01B.pdf` ... `cpu-stress05A.pdf`, `cpu-stress05B.pdf` | `anomaly_cpu/run01` ... `anomaly_cpu/run05` | Two-page export per run. The `A` page is the Sock Shop service panels; the `B` page is the host VM resource panels. |
| `disk-stress01A.pdf`, `disk-stress01B.pdf` ... `disk-stress04A.pdf`, `disk-stress04B.pdf`, `disk-stress05A.pdf` | `anomaly_disk/run01` ... `anomaly_disk/run05` | Same A/B layout as cpu-stress. **`disk-stress05B.pdf` is not present in this release** — only the service-panel page exists for `anomaly_disk/run05`. |
| `mem-stress01A.pdf`, `mem-stress01B.pdf` ... `mem-stress05A.pdf`, `mem-stress05B.pdf` | `anomaly_mem/run01` ... `anomaly_mem/run05` | Same A/B layout as cpu-stress. |
| `all-together-normal.pdf` | All `normal` runs | Multi-run overview placing the 5 normal runs side-by-side on the same dashboard. |
| `all-together-cpu-stress.pdf` | All `anomaly_cpu` runs | Multi-run overview across the 5 CPU-stress runs. |
| `all-together-disk-stress.pdf` | All `anomaly_disk` runs | Multi-run overview across the 5 disk-stress runs. |

### Known gaps in the PDF set

- **No Grafana PDFs are included for the network anomaly scenario** (`anomaly_net`).
  The raw traces and meta snapshots under `traces/anomaly_net/run01...run05` are
  complete; only the dashboard exports are missing for this scenario.
- **No `all-together-mem-stress.pdf` or `all-together-net-stress.pdf`** is included.
  Multi-run overviews exist only for `normal`, `cpu-stress`, and `disk-stress`.
- `disk-stress05B.pdf` is missing (only the `A` page exists for that run).

These gaps affect the PDF artifacts only. The raw `traces/` data for every
scenario / run is complete.

---

## How the data was collected

### Target system

The benchmarked application is the Weaveworks
[Sock Shop](https://github.com/microservices-demo/microservices-demo)
microservice demo, deployed via Docker Compose with the supplied monitoring
stack. The services traced in each run are:

```
front-end, edge-router, catalogue, catalogue-db,
carts, carts-db, orders, orders-db, payment, shipping,
user, user-db, queue-master, rabbitmq
```

Monitoring sidecars present in the deployment (Prometheus, Grafana, Alertmanager,
node-exporter, cadvisor) are visible in `meta/docker_ps_*.txt` and in the
kernel trace as scheduling/syscall activity, but they are not the subject of
the workload.

### Host

- Cloud VM: 12 vCPU, 40 GB RAM, 100 GB SSD (GCP).
- OS: Ubuntu 24.04, kernel `6.8.0-1052-gcp`.
- Hostname inside the captures: `lttng-traces-microservice`.
- Tracing tools: LTTng 2.15 (kernel + python UST), Babeltrace2.
- Docker: 27.x with Docker Compose.

### Tracing pipeline

Per run, the collection script (`collect_trace.sh`) does the following:

1. Creates a UST session (`sockshop-ust`) writing CTF to `<run>/ust/`, enables
   the `lttng_python` event `otel.spans`, and adds `vpid`/`vtid`/`procname`
   userspace contexts.
2. Creates a kernel session (`sockshop-kernel`) writing CTF to `<run>/kernel/`,
   enables all kernel events (`-k --all '*'`) and adds `pid`/`tid`/`procname`
   kernel contexts.
3. Starts both sessions and writes the `*_start` snapshots.
4. Starts the OpenTelemetry-to-LTTng relay
   (`agents/otel-to-lttng.py`) which subscribes to `docker logs -f` on the
   four Java services and forwards each `LoggingSpanExporter` line as a
   structured Python log record into the UST session.
5. Sleeps for the configured duration (100 s in this release) while the
   workload runs. A background loop writes `*_tick_<UTC>` meta snapshots every
   10 s during this period.
6. Writes `*_end` snapshots and tears the LTTng sessions down.

### Workload

Traffic is produced by a Python load generator
(`microservice-lttng-data-collection-scripts/load_generator.py`) that drives
the Sock Shop front-end through realistic user flows: browsing the catalogue,
viewing item detail pages, adding and removing cart items, registering and
logging in, placing orders, and querying order history.

Standard pacing across the runs in this release:

- 200 concurrent virtual users,
- think time uniformly between 0.1 s and 0.3 s per user,
- 100 s of measured load per run,
- a 20 s warm-up wait before measurement starts.

### Scenarios

Each scenario reuses the same tracing setup and the same load generator
configuration. The only difference is the optional fault injection running
concurrently with the load.

| Scenario | Fault injection |
|---|---|
| `normal` | None. Application runs under load only. Used as the in-distribution reference. |
| `anomaly_cpu` | `stress-ng --cpu <2× host CPUs> --cpu-method matrixprod --cpu-load 100` for the full run duration, saturating CPU and thrashing caches. |
| `anomaly_disk` | `stress-ng --hdd 300 --hdd-bytes 4G --hdd-opts direct,fsync`, generating heavy disk write pressure with `O_DIRECT` and per-write `fsync`. |
| `anomaly_mem` | `stress-ng --vm 24 --vm-bytes 95% --vm-method all --vm-keep --page-in`, allocating and continuously touching ~95% of host RAM. |
| `anomaly_net` | Linux `tc qdisc` on the Sock Shop Docker bridge interface: `netem delay 80ms ± 20ms (normal distribution) loss 0.5%`, layered with a `tbf rate 20mbit burst 64k latency 100ms` shaper. Applied a few seconds after tracing starts and removed on cleanup. |

The exact injection commands and parameters are reproducible from the
collection scripts in
`microservice-lttng-data-collection-scripts/{1_cpu_stress,2_disk_stress,3_mem_stress,4_net_stress}.sh`.

### Repetition

Each scenario was run five independent times (`run01`–`run05`). The repeats
are independent collection sessions on the same host, performed on the same
day (UTC timestamps in `traces/metadata.csv`), with the same software
versions and the same Sock Shop deployment. They are intended to support
per-scenario variance analysis and train/valid/test splits.

---

## Reading the traces

Both kernel and UST trace folders are standard CTF traces and can be opened
with any CTF-compatible reader. Examples with Babeltrace2 (must be installed
on the reader's host):

```bash
# Stream the kernel trace as text
babeltrace2 --output-format=text <run>/kernel/kernel

# Stream the UST (OTel relay) trace as text
babeltrace2 --output-format=text <run>/ust/ust/uid/1002/64-bit

# Count syscall_entry events
babeltrace2 <run>/kernel/kernel | grep -c "syscall_entry_"

# Pull OTel span lines for one trace_id from UST
babeltrace2 <run>/ust/ust/uid/1002/64-bit | grep "trace_id=6424612383807cd1189c15a8d3236908"
```

CTF traces can also be loaded programmatically:

- Python: `bt2` (Babeltrace2 Python bindings),
- C/C++: libbabeltrace2.

### Time alignment

Both LTTng sessions run on the same VM and use the same monotonic clock.
Kernel and UST event timestamps are directly comparable. The UST event payload
also includes `docker_ts` (from `docker logs --timestamps`) and `relay_ts_ns`
(set by the relay at forwarding time), which together quantify the export
latency of the Spring Boot span exporter.

---

## Known caveats

- **Single host.** Every trace in this release comes from one VM. Cross-host
  ordering, distributed clock skew, and multi-tenant interference are out of
  scope here.
- **Sock Shop is a benchmark, not production.** Service topology, request
  shape, and database load reflect the demo's design choices.
- **UST relay coverage is a subset.** Only `carts`, `orders`, `shipping`, and
  `queue-master` containers are tapped for OTel spans, because those are the
  Java services that emit Spring Boot `LoggingSpanExporter` output. Other
  services do not appear in the UST stream.
- **UST is export-time, not native span boundaries.** Each UST event records
  *that a span was exported*, not start/end of execution. For execution
  boundaries, prefer the kernel trace's `syscall_entry_*` / `syscall_exit_*`
  pairs.
- **`metadata.csv` may list duplicate `(scenario, run_id)` rows.** Earlier
  collection attempts were retried; the surviving on-disk run is the most
  recent attempt. See "Run-level `metadata.csv`" above.
- **Anomaly intensity is aggressive.** The default `stress-ng` parameters are
  chosen to produce clearly visible degradation in service-level signals.
  Subtler intensities can be reproduced by changing the script knobs
  (`CPU_WORKERS`, `DISK_WORKERS`, `VM_BYTES`, `NET_DELAY_MS`, etc.).

---

## Reproduction

The full collection toolchain ships in this repository:

- `microservice-lttng-data-collection-scripts/collect_trace.sh` — starts both
  LTTng sessions, manages the metadata snapshot loop, runs the OTel relay,
  tears everything down.
- `microservice-lttng-data-collection-scripts/0_normal_stress.sh` — normal-load
  run wrapper (no fault injection).
- `microservice-lttng-data-collection-scripts/1_cpu_stress.sh`,
  `2_disk_stress.sh`, `3_mem_stress.sh`, `4_net_stress.sh` — scenario
  wrappers that start tracing, run the fault injection, and drive load.
- `microservice-lttng-data-collection-scripts/load_generator.py` — workload.
- `microservice-lttng-data-collection-scripts/agents/otel-to-lttng.py` —
  OpenTelemetry-to-LTTng UST relay.
- `DOCS/final/reproduce_sock_shop_env.md` — host setup, Docker Compose reset,
  and verification steps for the Sock Shop deployment used here.
- `DOCS/final/micro-service-setup.md` — end-to-end setup notes (VM,
  Docker Compose, LTTng, Prometheus).

A typical reproduction step looks like:

```bash
# (1) Bring up Sock Shop with monitoring (see DOCS/final/reproduce_sock_shop_env.md)

# (2) On the same VM, run a normal scenario:
./microservice-lttng-data-collection-scripts/0_normal_stress.sh run01 100

# (3) Or an anomaly scenario:
./microservice-lttng-data-collection-scripts/1_cpu_stress.sh run01 100
```

Each wrapper writes its trace bundle to `~/traces/<scenario>/<run>/` and
appends to `~/traces/metadata.csv`.

---

## Licensing and attribution

- The traced application, Weaveworks Sock Shop, is licensed under Apache-2.0
  by Weaveworks. See <https://github.com/microservices-demo/microservices-demo>.
- The collection scripts and this dataset README are released for research use.
  See the repository LICENSE file (if present) for terms.

When using this dataset, please cite the repository or accompanying paper
(citation block to be added).
