# v2 campaign — known issues and what to do about them

**Live document.** Started 5 Sept 2026, while the campaign was running. Every entry says which
runs are affected and whether they need **re-collecting** (the data is wrong) or only
**re-scoring** (the data is fine, the verdict is not).

**The authoritative list is generated, not written here.** This prose went stale within two
hours of being written — the campaign kept producing runs. Run this on either VM:

```bash
python3 ~/microservice-trace-dataset/microservice-lttng-data-collection-scripts/campaign_issues.py
```

It reads the bundles and groups everything as RE-COLLECT / RE-SCORE / ACCEPTED, and it
classifies conservatively: anything it cannot prove is a data problem is reported as a
re-score, because that is the cheap remedy and the honest default.

`rebuild_manifest.py` gives the full per-run index. Neither uses the driver's own manifest,
which is unreliable for this campaign (issue 7).

The sections below explain **why** each class of problem exists — the generated list says which
runs are affected right now.

---

## The distinction that matters

| | meaning | cost |
|---|---|---|
| **RE-COLLECT** | the run does not contain the fault it claims | a VM run |
| **RE-SCORE** | the fault fired and the trace is clean; only the verdict is wrong | a re-run of `verify_injection` |
| **ACCEPTED** | a real property of the setup, recorded rather than fixed | nothing |

Re-scoring is possible **permanently and offline**: every bundle ships its own metrics export
(440 metric files, ~2.4 MB, all series the corrected targets need). It does not depend on
Prometheus retention or on the VMs still existing.

---

## 1. RE-COLLECT — `anomaly_net` injected nothing on Train Ticket

**Cause.** `stack_containers()` was hardcoded to `^docker-compose_.*_1$`. Train Ticket's
containers are `trainticket_*_1`, so netem was applied to **zero** interfaces. Ground truth
recorded `"containers": 0` and the runs were collected and labelled as network faults.

**Fixed** 5 Sept — `stack_containers` now lives in `fault_lib.sh` and follows `STRATA_APP`
(matches 44 containers on TT, including the unprefixed `mysql` and `nacos`). Verified: r3
recorded `containers=42`.

**Affected — already deleted, will be re-collected:**
- `tt_anomaly_net_aggressive_steady_r1`
- `tt_anomaly_net_aggressive_steady_r2`

**To re-collect:** re-run the driver after the campaign finishes. It skips every run that
already exists, so it will collect exactly the missing ones.
```bash
bash ~/microservice-trace-dataset/train-ticket-collection-scripts/run_campaign_tt.sh
```

**Also check** the `anomaly_net` **burst** variants when they run (`CAMPAIGN_WORKLOAD_FAULTS`) —
they will use the fix, but confirm `containers > 0` in their ground truth.

---

## 2. RE-COLLECT (already done) — a false positive reached the dataset

`tt_anomaly_net_aggressive_steady_r2` had `containers=0` — nothing injected — and was
certified **`confirmed`**. Its target was mysql's receive-byte rate with `direction=decrease`,
and mysql's inbound traffic drifts with load: 1665 → 864 scored `frac=1.0, sigma=-3.09`.

**A target that moves on its own can certify a fault that never happened.** This is the worst
failure mode available and it is the only one that actually landed. Deleted.

**Fixed** by registering TT `anomaly_net` as a known negative (`expected_to_fail`) — see issue 5.

---

## 3. RE-SCORE — thresholds written from the mechanism, never measured

20 of 22 canonical targets carried no evidence note; one literally said *"Finalize on VM
calibration."* Four distinct ways they were wrong:

| family | what was wrong | measured |
|---|---|---|
| `anomaly_disk` (SS) | target was a **bounded** metric our own tracing had already consumed | io_time 0.95x; writes/s **3.56x** |
| `anomaly_mem` (SS) | demanded a floor the fault cannot reach | needed <0.25, floor **0.40** |
| `anomaly_cpu` (TT) | sigma gate **mathematically impossible** | 5σ demands **124.9% CPU** |
| `dependency_outage` (SS) | sigma gate **mathematically impossible** | −2σ demands **−0.0008 cores** |

All fixed with measured numbers. **The data from these runs is good** — faults fired, ground
truth correct, traces clean.

**Affected (re-score only):**

*Sock Shop*
- `anomaly_disk_aggressive_steady_r1` … `r5`
- `anomaly_mem_aggressive_steady_r1` … `r5`
- `dependency_outage_aggressive_steady_r1`, `r2`

*Train Ticket*
- `tt_anomaly_cpu_aggressive_steady_r1`, `r2`
- `tt_anomaly_disk_aggressive_steady_r1`
- `tt_anomaly_mem_aggressive_steady_r1`, `r2`
- `tt_anomaly_net_aggressive_steady_r3`, `r4` (these **did** inject — r3 had `containers=42` —
  they predate the known-negative registration and should re-score to `no_metric_signature`)

**To re-score:** re-run `verify_injection.py` against each bundle with the current
`verification_targets*.json`. Needs a small adapter to read the bundle's metrics export instead
of live Prometheus — **not yet written**.

---

## 4. RE-SCORE or ACCEPT — a single borderline repeat

`queue_backlog_aggressive_steady_r2` is `borderline` while `r1` is `confirmed` (sigma −3.39).
Ordinary run-to-run variation, which is what five repeats exist to absorb. No threshold change
made. Check whether r3–r5 confirm; if 4 of 5 confirm, accept r2 as variation.

---

## 5. ACCEPTED — `anomaly_net` has no metrics signature on Train Ticket

Measured on r3 (42 containers, 80 ms delay, 20 ms jitter, 2% loss) — **nothing moves**:

```
tcp retransmits         0 -> 0          host netstat cannot see container netns
tcp out segments        2 -> 2          same reason
container tcp sockets   306.8 -> 302.9  0.99x
tx/rx packets dropped   0 -> 0          netem drops in the qdisc, not the interface
gateway recv bytes      1456 -> 1539    1.06x
```

**Structural, not a missing threshold.** netem adds *latency*; Sock Shop's target for this
family is application latency (`http_request_duration_seconds_bucket`), a histogram its services
expose and Train Ticket's do not. The same fault is metrics-visible on one application and
metrics-invisible on the other because of how they are instrumented.

Registered as `expected_to_fail` → reports `no_metric_signature`. **The fault is still
observable** — the load generator CSV records per-request latency. What this records is that the
*metrics modality* is blind to it, which is the kind of claim the ablation study exists to make.

---

## 6. ACCEPTED — the disk fault degrades the trace collector, on Train Ticket only

`tt_anomaly_disk_aggressive_steady_r4` → **`LOSSY:2481855`** (~0.25% of the run) while verifying
`confirmed`. One of five repeats; r1, r2, r3, r5 are clean.

LTTng writes ~176 MB/s to a disk that sustains 206 MB/s on Train Ticket. `anomaly_disk` adds
`stress-ng` `direct,fsync` writes and the consumer falls behind. Sock Shop traces at 53 MB/s,
has four times the headroom, and shows no loss on this family.

**Not "fixed", deliberately.** Bigger buffers only delay a sustained overrun and risk a failed
session (LTTng allocates at start); a weaker fault on Train Ticket would make `anomaly_disk` a
different experiment on the two applications.

**Related and worth carrying into the analysis:** the fault adds **+24 MB/s** on Train Ticket
against **+80 MB/s** on Sock Shop, because barely 30 MB/s of headroom remains after tracing.
The instrument does not merely fail to *see* the fault — it limits how large the fault can be.
"Disk saturation" is therefore **not the same experiment on the two applications.**

---

## 7. ACCEPTED (this campaign) — the driver's manifest says `n/a` for every fault run

The driver reads the verdict from `$RUN_DIR`, which no longer exists once the run is archived.
Fixed in git, **not** applied to the running campaign: bash reads scripts incrementally and
editing one mid-run can make it execute garbage.

**Use `rebuild_manifest.py`**, which derives the index from the bundles. `~/campaign_manifest.csv`
and `~/tt_campaign_manifest.csv` are unreliable for this campaign.

---

## 8. RE-SCORE — the five code defects have no verification targets at all

**25 Sock Shop runs report `no_targets`** (5 defects x 5 repeats).

I calibrated the ten new *fault* families on 4 Sept and prepared the same calibration pass for
the code defects — then never ran it; the cAdvisor findings took over. The defects were verified
to work (5/5 smoke, 5.14x / 6.14x / 39.98x / 16.41x plus memory growth against their own
`STRATA_BUG=none` controls), so the runs contain real defects. Nothing checks them.

`no_targets` is the honest status and it did its job: the gap is visible in every bundle rather
than silently absent. Candidate metrics are already defined in
`faults/measure_targets.sh` (`code_lock_across_io`, `code_n_plus_one` -> catalogue and DB CPU;
`code_event_loop_block`, `code_serial_awaits` -> front-end CPU and descriptors;
`code_unbounded_cache` -> front-end memory).

**Affected:** all `code_*_aggressive_steady_r1..r5` on Sock Shop.

---

## 9. RE-SCORE — Train Ticket families that were never calibrated

`slow_db` (5/5), `svc_cpu_cap` (5/5), `svc_net` (5/5), `error_storm` (2) are failing on Train
Ticket. All four were on the never-calibrated list, and all four use container CPU or network
byte rates as proxies — the same class of target that produced a false positive for
`anomaly_net` (issue 2), because those rates drift with load on their own.

Measure each against a completed run's own window before re-scoring, exactly as was done for
`anomaly_disk` and `anomaly_mem`. Do **not** carry Sock Shop's numbers across (standing rule 2).

---

## 10. Partial failures in calibrated families — check whether it is the threshold or variation

`fd_exhaustion` 3 of 5, `lock_contention` 3 of 5, `deadlock` 1 of 5 on Sock Shop.

These families *were* calibrated (4 Sept) and most repeats confirm, so this looks like
thresholds sitting too close to the effect rather than being wrong. Worth one look at a failing
and a passing repeat side by side before changing anything — `queue_backlog` showed the same
shape and turned out to be ordinary variation (issue 4).

---

## 12. ACCEPTED — `svc_cpu_cap` does not bite on Train Ticket

Measured on `tt_svc_cpu_cap_aggressive_steady_r1`:

```
ts-travel-service CPU   0.0033 -> 0.0060 cores      the cap is 0.2 cores
```

**The service uses 60x less CPU than the cap allows**, so the quota never binds. Train Ticket
spreads 20 users across 40 services, leaving each one nearly idle; Sock Shop concentrates the
same style of load on far fewer services. The fault is applied correctly and simply has nothing
to constrain.

Neither available metric can verify it:

- **usage** does not fall, because the cap is above the working set
- **`container_spec_cpu_quota`** persists after cleanup (see below), so it cannot time the
  injection window — it reads the same value before, during and after

`svc_cpu_cap` is therefore **not the same experiment on the two applications**, in the same way
`anomaly_disk` is not (issue 6). Worth stating in the paper rather than treating the Train
Ticket runs as comparable.

**Restore leaves Docker metadata behind, but the cgroup is clean.** Checked after the campaign:

```
docker inspect  ts-travel-service   NanoCpus=500000000   (0.5 cores)
cgroup          cpu.max             max 100000           (UNLIMITED)
docker inspect  ts-order-service    Memory=67418689536   (67 GB > the VM's 62 GB)
```

This is the documented trap — `--cpus=0` and `-m 0` are silent no-ops, so the recipes restore by
other means and `docker inspect` keeps a stale value. **CLAUDE.md's rule to verify restores
against `/sys/fs/cgroup/*` rather than `docker inspect` is correct and was worth following:** no
run was contaminated by a leftover cap.

---

## 13. RE-SCORE — `slow_db` and `svc_net` on Train Ticket still need calibration

Measured on r1 of each, and neither is conclusive from these candidates:

| family | strongest candidate | reading |
|---|---|---|
| `slow_db` | ts-travel-service CPU | 0.0030 → 0.0067 (2.22x) |
| `svc_net` | everything | **uniformly 2.1x** |

`svc_net`'s uniform rise across unrelated services (mysql 2.36x, travel 2.13x, basic 2.07x,
gateway 2.12x) looks like load variation over the window rather than a targeted network fault —
the same drift that produced the `anomaly_net` false positive. **Do not register it without
separating fault from drift**, e.g. by comparing against a `normal` run over the same clock
position.

10 runs affected (`slow_db` ×5, `svc_net` ×5). Data intact; verdicts outstanding.

---

## 14. ACCEPTED (not recoverable) — 103 Train Ticket runs have no load CSV

Found 6 Sept while checking the archive was ready to move. Sock Shop: 169 CSVs for 169 runs.
Train Ticket: **31 for 134**.

Which runs kept theirs is not random — it is exactly the families whose fault does not block a
request:

| kept | lost |
|---|---|
| `normal` 10/10, `anomaly_cpu` 5/5, `anomaly_disk` 5/5 | every other family, 0 or 1 each |

The `_load.log` for a lost run is **empty** — no traceback, no `[load] N requests` completion
line. The process was killed before reaching its final print. All 134 logs are in the archive, so
this was readable directly rather than inferred.

**Cause.** Train Ticket's `load_generator.py` wrote its CSV only after
`with ThreadPoolExecutor(...) as ex:` exited. That block waits for every worker with no timeout.
A worker checks the clock only *between* journeys, and a journey is ~5 sequential requests at a
30 s timeout — so under a fault that blocks requests it overshoots the run by up to ~150 s.
`run_scenario.sh`'s cleanup trap killed the generator well before that, with every row still in
memory. Sock Shop's generator sets a stop event and bounds its join at 15 s, then always writes;
it lost nothing. The two generators were written to share a CLI and a CSV schema, and nobody
compared their shutdown paths.

**Fixed** in `train-ticket-collection-scripts/load_generator.py`: the write is a shared function
reachable from three paths — normal completion, a bounded `duration + 20 s` deadline, and a
`SIGTERM` handler. Verified against a host that accepts connections and never answers: the CSV
lands at the deadline and the process exits at once instead of hanging for the request timeout.

**Why ACCEPTED and not RE-COLLECT.** The rows only ever existed in the killed process's memory,
so nothing can be reconstructed from what is on disk. Re-collecting 103 Train Ticket runs is
~620 GB and about a day of VM time to recover one modality of four. The kernel trace, spans,
container logs and Prometheus export are complete in all 134 runs. It bites hardest on
`anomaly_net`, where the load CSV was the stated fallback for a fault with no metrics signature
(issue 5) — that fallback does not exist on Train Ticket, and the inventory has been corrected.
Whether to re-collect is a research call about what the ablation study needs, not a defect to
patch quietly.

---

## 15. ACCEPTED (affects analysis) - baseline host CPU drifted during the campaign

Found 7 Sept while testing blueprint 1, from 62 runs measured with `oncpu_share.py`. Ordering
every run by its collection timestamp shows baseline host utilisation moving with **time, not
family**, on both applications and in opposite directions.

**Train Ticket - a sharp step, 4.6x:**

| collected | families | baseline util |
|---|---|---|
| 07:37 - 12:02, 5 Sept | `normal`, `anomaly_cpu` | 0.626 - 0.709 |
| 18:08 onward | `noisy_neighbor`, `svc_cpu_cap` | **0.138 - 0.145** |

**Sock Shop - a gradual rise, 1.6x:** 0.514 -> 0.549 (`normal`), 0.567-0.592 (`noisy_neighbor`,
5 Sept), 0.609-0.624 (`svc_cpu_cap`), **0.794-0.814** (the 6 Sept re-collected runs).

**Why it matters, twice over.**

1. **Any threshold on ABSOLUTE host utilisation is partly measuring collection time.** This is
   not hypothetical - it is what broke the co-tenant blueprint's `CONTENDED = 0.55` clause on
   Train Ticket, where healthy runs sit at 0.66-0.71 and genuinely contended runs at 0.21-0.28.
   The ordering inverts. Deltas (thief cores gained, utilisation ratio) are unaffected and
   scored 100%.
2. **A fault's measured magnitude depends on when it ran.** Sock Shop `svc_cpu_cap` collapsed
   host CPU to 0.25x of baseline on 5 Sept and only 0.87x on 6 Sept - same recipe, same
   intensity, same target. Any cross-run comparison of effect size on Sock Shop has to state
   the collection time.

**The data is not wrong** - every run is internally consistent, with its own baseline window
measured beside its own incident window. What cannot be done is comparing absolute utilisation
across runs collected hours apart.

**Cause not established.** The Train Ticket step falls in the gap where the campaign was
stopped, reset and restarted (issue 17), which is suggestive and not evidence. Recorded as an
open question. The remedy for analysis is available now and costs nothing: prefer within-run
ratios over absolute levels.

---

## 11. Things to verify before the campaign ends

- [ ] `anomaly_net` **burst** runs on TT record `containers > 0`
- [ ] `queue_backlog` r3–r5 on SS confirm (issue 4)
- [ ] No new `LOSSY` runs beyond `tt_anomaly_disk_r4`
- [ ] The **code-defect** families (Sock Shop only, near the end of the matrix) verify — their
      targets were calibrated 4 Sept but have never run inside a campaign
- [ ] The **subtle** intensity variants verify — every threshold so far was measured against
      `aggressive`, and subtle is by design a smaller effect
- [ ] Write the offline re-scoring adapter (issue 3) before the VMs are deleted

---

## Standing rules learned the hard way

1. **An idle baseline is not a run baseline.** Two thresholds went vacuous because they were
   measured on a system that was not doing what it does during a run.
2. **A threshold calibrated on one machine is a guess on another** — and the dangerous direction
   is when the new machine's baseline already satisfies it.
3. **Sigma is delta ÷ baseline noise**, so a noisy or tiny baseline silently raises the bar past
   the metric's own range. `verify_injection` now records `sigma_required_value` so an impossible
   gate is visible in the bundle.
4. **Never `git pull` on a VM with a campaign running.** Use
   `git checkout origin/<branch> -- <one file>`. Per-run scripts are safe; the drivers are not.
5. **Every edit to a file you cannot immediately re-read needs an assert.** One unasserted
   `.replace()` matched nothing, changed nothing, and said nothing.
6. **Two ports of the same tool need their shutdown paths compared, not just their CLIs.** The
   Train Ticket load generator matched Sock Shop's flags and CSV schema exactly and still lost
   77% of its output, because only the teardown differed.
7. **Count every artefact per run, not just the bundle.** 303 bundles were complete and audited
   while a whole modality was missing from a third of them. Nothing failed loudly; the file was
   simply absent.

---

## Issue 16 — the trace collector's own disk writes contaminate the disk signal

**Found 2026-09-13. Affects analysis, not collection. No re-collection needed.**

`lttng-consumerd` writes the trace to the same disk it is tracing, so it appears as a process
"arriving on the disk" in most runs. Measured over 272 runs:

| | disk requests/s gained by the arriving process | who |
|---|---|---|
| healthy run | 37 – 66 | `lttng-consumerd` |
| `nagle_delayed_ack` | 945 – 1058 | `lttng-consumerd` |
| real disk fault | 698 – 2015 | the injected load generator |

The tracer's writes scale with how many events the workload produces, so a fault that changes
event volume moves the disk signal even when it touches no disk.

**Consequence before the fix:** `host-disk-saturation` fired on all 10 `nagle_delayed_ack`
runs — a network stall reported as a disk flood, 10 times out of 10, with a confident
well-formed verdict naming the wrong process.

**Fixed in analysis** (`blueprint_decide.py`): `lttng` added to the infrastructure list, and
the disk rule now refuses to name an infrastructure process as the flooder. Removed all 10
false diagnoses, cost no recall.

**Still worth checking elsewhere:** any measure whose newcomer can be `lttng-consumerd`.
`service-memory-cap` also reports it as the arriving process in several runs, though its ratio
falls below the bar so it does not currently fire on it. `io_newcomer` is stored as a single
value in the pack, so the rule can only veto — it cannot fall back to the next non-instrument
process. Recomputing that would need a pack rebuild.

Full write-up: `blueprints/docs/RESULTS-antipattern-ceiling.md`.

---

## Issue 17 - the five code-defect families have contaminated BASELINE windows

**Found 2026-09-13. NEEDS RE-COLLECTION. 25 runs, Sock Shop only.**

`code_defect_dispatch inject` does this, in this order:

```
code_defect_apply "$DEFECT_BUG" "$DEFECT_IMAGE"   # restarts the container, sleep 6, verify
gt_begin ...                                       # incident window starts HERE
```

The container restart happens **before** the incident is declared, so it lands inside the last
seconds of the 60-second baseline window. The baseline is not a healthy reference - it contains
a container teardown and restart.

Measured, retransmission in the BASELINE window (a healthy baseline measures 0.00%):

| family | baseline retransmission | runs affected |
|---|---|---|
| `code_lock_across_io` | 65.4 - 73.2% | 5 of 5 |
| `code_n_plus_one` | 34.7 - 79.9% | 5 of 5 |
| `code_serial_awaits` | 30.4 - 71.2% | 5 of 5 |
| `code_event_loop_block` | 28.6 - 61.4% | 5 of 5 |
| `code_unbounded_cache` | 0 - 53.9% | 3 of 5 |
| every other family | 0 - 5.6%, mostly 0 | - |

Corroborating: 3-7 endpoints "gone" between windows in every code run, against 1-2 elsewhere.
That is containers coming back on new addresses.

**Consequence.** Every baseline-relative measure in these 25 runs is a ratio against a restart.
`node|poll` reads 1700x not because the defect is dramatic but because the baseline was a
service being torn down. This is why no signal separates these families - the dominant thing in
the data is the injection mechanism, not the fault.

**This violates a rule the project already holds.** CLAUDE.md: Toxiproxy sits permanently in
the catalogue path *because "fault toggling must be restart-free"*. The code-defect recipes
toggle by restarting with a different `STRATA_BUG` environment variable.

**Fix for re-collection** - either:
1. gate each defect behind a runtime switch (a file, or an HTTP endpoint) so it can be turned
   on without a restart, which is what toxiproxy does for `slow_db`; or
2. restart with the defect already enabled, let it settle, and only then start tracing - so
   the restart is outside the measured window entirely.

Option 1 is better: it also gives a genuine paired control on the same process.

**Until re-collected, these 25 runs must not be used for any baseline-relative claim.**
They remain valid as incident-window evidence, which does not involve the baseline.

### FIX WRITTEN 2026-09-13 - not yet run on hardware

Option 1 above is implemented. The defect gate now reads `/tmp/strata_bug` inside the
container, falling back to the `STRATA_BUG` environment variable, so it can be flipped without
a recreate. The recipe verb set is now:

| verb | what it does | restarts? | when |
|---|---|---|---|
| `arm` | put the service on the defect image with the defect OFF | **yes** | before tracing starts |
| `inject` | write the defect name into the flag file | no | at baseline+60s, as before |
| `cleanup` | write `none` back | no | at the end of the incident window |
| `disarm` | restore the stock image | **yes** | after tracing ends |

`run_scenario.sh` arms before `collect_trace.sh` opens and disarms after it closes, with a
20-second settle after arming so the recreated container's startup is not the first thing in
the baseline. `inject` **refuses to run un-armed**, so a missed arm fails loudly instead of
quietly producing another 25 contaminated runs.

Changed: `faults/code-defects/inject_defects.py` (both the Go and the Node gate),
`faults/code_defect_lib.sh`, `run_scenario.sh`, `faults/code-defects/smoke_defects.sh`.

**I have not run any of this.** The collection VM was deleted on 2026-09-07, so there is
nowhere to build the images or start the stack. What has been checked: the Python parses, the
generated Go and JavaScript were printed and read, and every shell file passes `bash -n`.
Whether the patched services still build and serve traffic is unverified.

**Before the next campaign, in this order:**
1. `bash faults/code-defects/build_defect_images.sh` - this runs `inject_defects.py --check`
   first, so a broken anchor is caught before any image is built.
2. `bash faults/code-defects/smoke_defects.sh` - confirms each defect still changes something
   measurable against its own control, now through the file flag.
3. One `code_n_plus_one` run end to end, then check baseline retransmission is back to 0.00%.
   That single number is the whole point of this fix.

Full analysis: `blueprints/docs/COVERAGE-which-blueprints-are-missing.md`.

---

## Issue 18 - RETRACTED. Campaign verification works and is where the code expects it

**Logged 2026-09-13, retracted the same day.**

I claimed `verification.json` did not exist anywhere in v2 and that
`derive_v2_thresholds.py:confirmed()` could never return True. **Both claims were wrong.**

The cause was my own shell quoting: a `V2=...` assignment inside a nested `ssh "..."` command
silently expanded to empty, so `find` searched the home directory and returned nothing. I read
that as evidence and wrote it up.

What is actually there:

| | count |
|---|---|
| run bundles | 303 |
| `ground_truth.json` | 283 |
| `verification.json` | 283 |
| `verification.png` | 283 |

283 = every fault run. The other 20 are the `normal` controls, which are skipped by design.
The path is exactly the one `confirmed()` reads.

**And the verification caught the bad runs.** All four runs my kernel-side analysis flagged as
inert had already been flagged by the campaign months earlier:

| run | verification said |
|---|---|
| `dns_delay_aggressive_steady_r4` | `no_metric_signature` |
| `tt_slow_db_subtle_steady_r3` | `unconfirmed` |
| `tt_svc_net_aggressive_steady_r2` | `unconfirmed` |
| `tt_svc_net_aggressive_steady_r5` | `borderline` |

So the campaign's own quality gate worked. The failure was downstream: **nothing in the analysis
reads `verification_status`**, so unconfirmed runs were used as positives when deriving
thresholds and as negatives when testing separation. That is the real defect, and it is
Issue 19.

**Lesson, and the reason this is kept rather than deleted:** I asserted that a quality control
had never run, on the strength of one command that returned zero. A zero from a search is not
evidence of absence until the search itself is verified. The `fd-exhaustion` blueprint's
"campaign-confirmed" claim, which I called unreproducible, is reproducible.

---

## Issue 19 - the analysis ignores `verification_status`

**Found 2026-09-13. Affects analysis, not collection.**

283 runs carry a verification verdict and **no analysis script reads it**. Consequences that
have already happened:

- `dns_delay` was scored 4/5 with the fifth counted as a miss. It is not a miss - the campaign
  recorded `no_metric_signature`, meaning the injection did not take. It should be excluded, and
  the blueprint is 4/4 on runs that contain the fault.
- The `tt_svc_cpu_cap` and `tt_slow_db` families are entirely `unconfirmed`/`borderline`, and
  were used as positives throughout.

**FIXED 2026-09-13.** `blueprints/lib/verification.py` holds the index and the policy;
`results/verification_index.json` carries the status of all 303 runs. Wired into
`build_ruler.py`, `sweep_uncovered.py` and the new `score_with_verification.py`. Every script
that filters PRINTS what it filtered - a filter nobody can see is how this happened.

What it changed, measured:

| | every labelled run | only runs whose fault took |
|---|---|---|
| correct | 85/116 (73%) | **82/91 (90%)** |
| false fires | 46 | **49** |

Both move, in opposite directions. 22 of the 31 "misses" were runs with no fault to find. 3
runs where a blueprint fired were counted as hits because the run carried a fault label; the
fault did not take, so firing on them is a false fire.

**The policy:** a non-confirmed run is excluded as a POSITIVE and kept as a NEGATIVE. Removing
it from both sides would improve the score by deleting the evidence.

**What it exposed.** Three Train Ticket families have no verified run at all - `slow_db`,
`svc_cpu_cap`, `svc_net`. `svc_cpu_cap` scoring "0/8" was never a blueprint failure; there was
nothing in those eight runs to find. Two Sock Shop families have none either:
`code_lock_across_io` and `code_n_plus_one` are 0 of 5 confirmed. The sweep now reports
"NO VERIFIED RUN" and stops, rather than fitting a cut to runs that contain no fault.

One correction to the note above: `dns_delay` r4 is `no_metric_signature`, which does NOT mean
the injection failed - it means no metric target can see this fault. The kernel shows it in 4
of the 5 runs. r4 is a genuine failed injection, but the status alone cannot say so.

Full write-up: `blueprints/docs/RESULTS-verification-filter.md`.

---

## Issue 20 - ACCEPTED: the baseline window includes the load generator ramping up

**Found 2026-09-15. Affects analysis. Deliberately NOT fixed - see the decision below.**

`run_scenario.sh` starts the load generator and immediately begins the baseline sleep, so the
baseline window is `[load_start, load_start + 60s]`. The load takes roughly 25 seconds to spin
up to 150 users, which means the first ~25 seconds of every 60-second baseline carries little
or no traffic.

Measured on `code_lock_across_io_aggressive_steady_r1`, catalogue request rate across a whole
run:

| time, relative to injection start | requests/s |
|---|---|
| -70 s | 0.2 |
| -40 s | 153.0 |
| -20 s | 261.9 |
| **0 s (injection starts)** | **264.1** |
| +120 s (injection ends) | 263.7 |

The rate steps up **40 seconds before the injection** and is flat across the injection
boundary.

**Consequence.** Baseline rates are understated, so every incident-against-baseline ratio is
somewhat inflated. It does not change which runs contain their faults, and it does not touch
anything measured inside a single window.

**How it was found.** Not by looking for it. I changed a code-defect verification target to
expect a rate INCREASE, having seen 110.8 -> 273.5 on one run and reasoned that an N+1 defect
issues more queries. The run confirmed. Then `code_lock_across_io` - a mutex held across I/O,
a completely different fault - produced 101-109 -> 252-260, the same number. Two unrelated
defects cannot share a signature, and plotting the rate showed why.

**DECISION (Yuvraj, 2026-09-15): leave it.** All 303 v2 runs were collected this way, so the
distortion is uniform across the dataset and the re-collected runs stay directly comparable
with the ones they replace. Replacing contaminated runs with clean-but-incomparable ones would
trade a known problem for a worse one.

Fix it deliberately in a future collection, not mid-campaign: either start the load generator
before tracing opens, or add a settle period before the baseline window begins. Both are the
same shape as the `arm`-before-tracing fix in issue 17.

**Do not "discover" this again and change it in place.** A run collected with a settled
baseline is not comparable with the 303 that were not.

---

## Issue 21 - RESOLVED: issue 17 re-collection done, and two code defects turned out metric-visible

**Closed 2026-09-15.** All five code-defect families re-collected on the replacement VM with the
`arm`/`inject` split from issue 17. **26 of 26 runs usable** (25 campaign + 1 proof run).

While re-verifying them, the shared canonical target caught something the old contaminated runs
could not show. Catalogue request rate, median of 5 runs per family:

| family | baseline | injection | recovery | reads as |
|---|---|---|---|---|
| `code_lock_across_io` | 106.5 | 262.2 | 262.7 | ramp only |
| `code_n_plus_one` | 104.1 | 255.9 | 255.0 | ramp only |
| `code_unbounded_cache` | 99.8 | 245.9 | 247.2 | ramp only |
| `code_event_loop_block` | 102.8 | **34.3** | **122.4** | real |
| `code_serial_awaits` | 93.6 | **50.5** | **132.4** | real |

**Read the recovery column, not the baseline.** Baseline is contaminated by the load ramp (issue
20), so baseline-to-injection ratios mean little. Injection-to-recovery is clean: both windows run
the identical container image, and only the `/dev/shm` flag differs. Where injection equals
recovery, nothing happened. Where the rate falls and then returns, the fault is real.

Both visible families are front-end Node defects - a single-threaded event loop, so blocking it
stalls every request. The three invisible ones are Go in catalogue, where concurrency absorbs the
per-request slowdown and offered throughput does not change.

**Targets updated:** the two visible families lost `expected_to_fail` and now verify normally;
the other three keep it and report `no_metric_signature`.

**Two caveats carried forward, neither resolved:**

1. `sigma_ok=false` on both visible families. The load ramp inflates `baseline_std`, so the sigma
   test cannot fire. Verdicts rest on direction + fraction, corroborated by recovery. Another
   consequence of issue 20.
2. Settled catalogue rate is ~130/s in front-end-defect runs but ~250/s in catalogue-defect runs
   under the same load profile. Within-run comparisons are unaffected. **Do not compare absolute
   rates across the two groups** until this is explained.
