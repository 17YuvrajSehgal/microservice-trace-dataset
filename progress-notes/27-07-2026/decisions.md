# Progress notes — 27-07-2026

## Decisions & verification record

### 1. Phase-0 rig committed after independent re-verification (commit 9a44380)
The Phase-0 four-modality changes (drafted and first verified 25-07-2026, see
that day's §8) were re-verified from scratch before committing, rather than
trusting the earlier session's notes:
- Collector 0.157.0 end-to-end with the repo's actual config: OTLP/HTTP test
  span → `otlp-out/spans.jsonl`, one JSON object per line. Receivers bind
  `0.0.0.0` as required for cross-container access.
- `bash -n` clean on `collect_trace.sh` and `download_metrics_full.sh`.
- Byte-offset slice arithmetic (`tail -c +offset+1`) exact, no off-by-one.
- Clock-anchor snippet returns REALTIME/MONOTONIC/BOOTTIME at ns precision on
  Linux Python 3.12.

### 2. Full-stack conformance verified against the plan (no VM needed)
Strongest possible off-VM check: rendered the exact four-file compose merge
from the usage headers (`docker compose … config` from the submodule deploy
dir) and asserted the modality wiring in the output:
- otel-collector service present, image pinned, `otlp-out` mount correct;
- every Java service carries javaagent `JAVA_OPTS` + `OTEL_SERVICE_NAME`;
- **our `prometheus-cadvisor.yml` wins the merge** for
  `/etc/prometheus/prometheus.yml` (merge-by-target-path confirmed in the
  rendered stack), while upstream's `alert.rules` mount survives;
- cadvisor service present (pinned v0.49.1) and in the scrape config.
Additionally: `promtool check config` passes against the **unpinned
`prom/prometheus` image the VM will pull** (config + 1 rule file resolve);
`docker logs --since <UTC>` windowing verified exact (pre-bound line
excluded, post-bound line returned).

**Reporting note:** this "verify everything off-VM before touching the VM"
discipline is worth one sentence in the paper's reproducibility section —
every collection-rig component is testable without LTTng hardware except the
LTTng sessions themselves.

### 3. Known-caveat record (for the datasheet)
- Upstream compose warns `MYSQL_ROOT_PASSWORD` is unset (blank root password
  on catalogue-db). Pre-existing upstream behavior, identical in the prior
  148 GB collection — not introduced by our overlays; harmless on an
  isolated research VM but must be stated in the datasheet's security note.
- Compose `version:` attribute warnings are cosmetic (upstream files are
  Compose v2 format; the attribute is ignored by current Compose).

### 4. Repo pushed to GitHub
`https://github.com/17YuvrajSehgal/microservice-trace-dataset` — includes the
Phase-0 rig commit and the submodule pin to the
`17YuvrajSehgal/microservices-demo` fork (9dff06f). Service forks
(`front-end`, `catalogue`) exist on GitHub, unmodified so far.

### 5. WSL2 rehearsal considered and declined — VM-only for LTTng
The local WSL2 kernel (6.6.114.1-microsoft-standard) does support modules/
tracepoints, so an lttng-modules build was feasible in principle, but the
setup cost (kernel-source build for headers + native docker-ce to avoid the
Docker Desktop pid-namespace skew on the kernel↔container join) is not worth
it. **Standing split:** local PC = pipeline mechanics, image builds,
userspace fault recipes (Toxiproxy/docker-update/pause), analysis code;
VM = everything touching LTTng, tc/netem, performance numbers, or published
data. VM work is tracked in `vm-todo.md` (this folder).

### 6. Tier-1 front-end instrumentation done and locally verified
Fork branch `17YuvrajSehgal/front-end@otel-instrumentation` (c11b5d9);
opt-in overlay `docker-compose.frontend-otel.yml` (5-file merge verified).
Decisions with rationale:
- **Base image node:10-alpine → node:20-alpine.** Node 10 (EOL 2021) is
  below every OTLP-capable OTel JS release. App deps are pure JS; verified
  the app boots and serves on Node 20 unchanged. This is the *only* runtime
  change — keeps the "minimal, documented fork diff" discipline.
- **Zero-code instrumentation, opt-in at deploy time** via
  `NODE_OPTIONS=--require @opentelemetry/auto-instrumentations-node/register`
  (deps baked into image, activation via env) — same overlay-controlled
  pattern as the Java agent; the image runs untraced without the env var.
  Pinned: api 1.9.1, auto-instrumentations-node 0.79.0.
- **CMD `npm start` → `node server.js`**: NODE_OPTIONS otherwise instruments
  the npm wrapper process too (observed: duplicate OTel init, pids 1+18).
- **`OTEL_NODE_RESOURCE_DETECTORS=env,host,os,process,serviceinstance`**:
  the default (all) probes GCP/AWS/Azure metadata services at startup and
  flooded the trace with multi-second dns.lookup/tcp.connect spans + blocked
  first requests. Keep the same list on the VM for span-stream consistency.
- Verified end-to-end locally: `GET /` produces a kind=SERVER span with the
  full Express middleware chain (query→expressInit→serveStatic), exported
  OTLP/gRPC → collector → spans.jsonl.
**Verification gotcha (for future local tests):** PowerShell
`Invoke-WebRequest` against Docker-published localhost ports can hang
(IPv6 localhost); `curl.exe` returned HTTP 200 in 0.23 s on the same
endpoint. Use curl for local HTTP checks.
**VM follow-up added to vm-todo.md**: build `frontend-otel:phase0` from the
fork branch on the VM before adding the overlay.

### 7. Tier-1 catalogue (Go) instrumentation done and locally verified
Fork branch `17YuvrajSehgal/catalogue@otel-instrumentation` (0d18219);
opt-in overlay `docker-compose.catalogue-otel.yml` (6-file merge verified).
Decisions with rationale:
- **gvt/GOPATH → Go modules (Go 1.23)**: mandatory for OTel Go. Notable:
  upstream's build fetched deps *unpinned at image-build time* (only
  vendor/manifest was tracked) — the old image was never reproducible.
  go.sum now pins everything. go-kit pinned v0.4.0; two API drifts vs the
  2016 SHA the code targeted had to be adapted (NewServer ctx arg ×5,
  log.NewContext→log.With) — everything else untouched.
- **Dormant Zipkin wiring removed** (never active: ZIPKIN env unset in our
  deployment) instead of migrating it — its ancient thrift dependency chain
  was the biggest modules-migration risk. go-kit layers get a NoopTracer;
  real spans come from an otelhttp wrapper with route-template span names
  ("GET /catalogue/{id}").
- **weaveworks/common middleware replaced by ~40-line local equivalent** —
  metric name + label set byte-identical (verified in /metrics output:
  http_request_duration_seconds{method,path,status_code,isWS}) so the
  metrics modality's scrape is untouched. Avoids dragging in the whole
  weaveworks/common dependency tree.
- **/metrics requests excluded from tracing** (otelhttp.WithFilter): at 5s
  scrape interval they would add ~720 self-observation spans/hour/service —
  cross-modality contamination (metrics collection polluting traces).
  Verified: /metrics=200 with no span. Consider same exclusion semantics
  for other services when instrumenting (Java agent has equivalent config).
- Verified end-to-end with real catalogue-db: /catalogue returns DB rows,
  kind=SERVER spans with route templates exported OTLP/gRPC, histogram
  continuity, /health span present. (Note: /health *blocks* when the DB is
  absent — upstream behavior, its handler queries the DB; not a regression.)
- Upstream `go vet` finding fixed in passing: unbuffered signal.Notify
  channel. (Upstream test-file vet warning left as-is.)

### 8. Sibling packages vendored — repo is now self-contained for baselines
`models/` (LSTM, Transformer + support modules) and `dataset/` (Dictionary,
IterableDataset) copied verbatim from `adaptive_tracer` at
`405e49e` ("added 100 user results", 2026-03-31; the only dirty files there
were untracked result tables, so the SHA cleanly describes the copy).
Layout matches what every `microservice/` script expects (repo root on
sys.path). `IterableDataset.py` included because `dataset/__init__.py`
imports it — any `dataset.*` import executes the package init.
**Verified** in a clean python:3.12 + torch-cpu container: all three import
patterns used by the analysis code work (package import of models, package
import of Dictionary + instantiation, path-based importlib load).
**Rule going forward:** the vendored copies are authoritative for this repo
(VENDORED.md in each dir); fixes land here, not in adaptive_tracer.

### 9. Cross-modality audit tool built and verified (audit_alignment.py)
`microservice-lttng-data-collection-scripts/audit_alignment.py` — the Phase-0
gate tool: given a run bundle (+ optional load CSV / metrics dir), picks a
trace (explicit or slowest server span) and prints the aligned view across
all modalities + a per-modality verdict. Design decisions:
- **Stdlib-only Python** — no pip installs on the VM.
- **Every section degrades gracefully** (partial bundles still audit; kernel
  section requires babeltrace2 and says so instead of failing).
- **Kernel attribution** joins babeltrace2 output (`--clock-gmt --begin
  --end` window trim) to containers via the meta/ docker-top tid maps —
  the same pid↔service join the study's L1/L2 derivers will use.
- **Clock verdict** computes realtime−monotonic offsets from the runinfo
  anchors at start/end and reports drift — the plan's measured-alignment
  claim in one number.
**Verified** on a synthetic bundle built around the real catalogue span
fixture: all in-window records surface (trace-id log line starred), all
three out-of-window decoys excluded, drift math exact (0.400 ms as
constructed). Kernel section = VM verification (needs CTF + babeltrace2).
This script is the seed of the loader SDK's alignment test (Phase 3).

### 10. Fault recipes built and mechanically verified (Phase-1 head start)
`faults/` now holds fault_lib.sh + 7 recipes (slow_db, error_storm,
svc_cpu_cap, svc_mem_cap, dependency_outage, queue_backlog, noisy_neighbor)
+ README with the **pre-registered fault→modality prediction table** —
committed before any ablation experiment runs, per the plan's narrative
design. Key decisions & findings:
- **Toxiproxy is ALWAYS in-path** (docker-compose.toxiproxy.yml): toggling
  toxics via API is instant and restart-free; inserting a proxy only for
  fault runs would pollute every modality with restart artifacts. Cost:
  constant sub-ms hop in all scenarios incl. normal (measured locally:
  baseline through proxy ≈ direct baseline at 0.22 s). Recipes toggle via
  the :8474 API.
- **Every recipe writes ground_truth.json** (fault_lib.sh) with exact
  injection window, params, target, blast radius, pre-registered winner,
  `target_trace_visibility`, and remediation — the §6 schema seeded at the
  recipe level.
- **Verified end-to-end locally** with the instrumented catalogue:
  slow_db 0.22 s → 1.1–1.3 s → 0.21 s; error_storm 200 → 500s → 200 with
  the predicted log evidence ("connection reset by peer", "driver: bad
  connection") — the logs-win pre-registration already has empirical
  support.
- **Three docker-update API gotchas found by testing restore paths against
  cgroup truth** (would have silently corrupted recovery windows):
  (1) `--cpus=0` is a no-op, the real unlimited-reset is `--cpu-quota=-1`;
  (2) memory limits CANNOT be cleared at all — restore approximates with
  host MemTotal, recorded in ground truth; (3) docker leaves NanoCpus
  stale after quota resets, so recipes capture both representations.
- **Port-80 bug caught in catalogue-otel overlay**: stock image runs
  `/app -port=80`, fork Dockerfile says 8080 — the image swap would have
  broken front-end→catalogue on the VM. Overlay now pins
  `command: /app -port=80`.
- Windows testing gotcha: PowerShell splits unquoted `-host=0.0.0.0` at the
  dots (toxiproxy bound host "0"); quote such args. Compose YAML unaffected.

## Open items (carried from 25-07-2026)
- **Phase-0 gate:** deploy the extended stack on the GCP VM, run one 30 s
  sample, hand-audit ONE request across all four modalities (load CSV → OTLP
  span tree → logs → metrics window → kernel syscalls via pid↔container
  join). Everything up to this gate is now verified.
- ~~Vendor `models/` + `dataset/Dictionary.py` from `adaptive_tracer`~~ —
  done (§8).
- Venue split decision with mentor (MSR technical track vs FSE/EMSE for the
  study paper).
- Dataset name collision check (FourSight / KODA / ModSense).
