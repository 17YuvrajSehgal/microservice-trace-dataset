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

## Open items (carried from 25-07-2026)
- **Phase-0 gate:** deploy the extended stack on the GCP VM, run one 30 s
  sample, hand-audit ONE request across all four modalities (load CSV → OTLP
  span tree → logs → metrics window → kernel syscalls via pid↔container
  join). Everything up to this gate is now verified.
- Vendor `models/` + `dataset/Dictionary.py` from `adaptive_tracer`.
- Venue split decision with mentor (MSR technical track vs FSE/EMSE for the
  study paper).
- Dataset name collision check (FourSight / KODA / ModSense).
