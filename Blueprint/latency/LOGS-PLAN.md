# Plan for the logs component

Status: **plan, 25-11-2026. Nothing in sections 4 to 9 is built.** What exists today is listed
in section 2. The decisions taken so far are in section 11; what is still open is in section 12.
After the first sweep starts, the scoring rules of section 8 change only with a dated note at
the end of this file.

Read with: `METHOD.md` (how a blueprint is built), `EVALUATION-PLAN.md` (arms and splits),
`Blueprint/agent/bp_graph.py` (the harness).

## 1. Goal, and the one rule

Add application logs to the blueprints so that an investigation can:

1. find the time of a fault faster,
2. **narrow where to look** when nobody knows where to start: a shortlist of services, and the
   kinds of fault their messages suggest (section 6.5; added 26-11 at the user's request),
3. say more than the kernel can ("who resets" becomes "who resets, and what it logged"),
4. point at the code that printed a message, where the source is connected.

**The rule: logs are a witness, the kernel check is the judge.** A log step may propose a time,
explain a confirmed verdict, or point at code. It never confirms a fault and never rejects one.
The only exception is a sub-label inside a blueprint whose text already says "the trace cannot
tell", and only after a sweep shows that logs separate the two cases (section 6.3).

Logs are always optional. A trace with no logs runs every blueprint exactly as today.

## 2. What we build on

### 2.1 Measured in the INQUEST paper (`C:\workplace\JiraAndLogs\industry-c7`)

| # | Fact | Source | What we take from it |
|---|---|---|---|
| 1 | In 49% of reports no fixed file is named. A matched log line's printing file was a fixed file in 40% (Kafka), 17% (MariaDB), 15% (MongoDB), 0% (Qt) of cases | paper sec. 1; `data/results/c7-log-sites.json` | The service that logs is not the culprit by default |
| 2 | Staged procedure against a free loop, same model and tools: file Acc@1 68.6 vs 67.9 (a tie), function Acc@1 53.8 vs 39.8 (+14.1) | paper table "ablation" | Logs enter as steps with fixed answers, not as free tools |
| 3 | The free loop did not stop by itself in 83.2% of runs; 72.7% of its reads re-read a file | `agent/workflow.py` header | Evidence is gathered by code before the model decides |
| 4 | Removing one decisive line costs 48% of what removing every file mention costs | `paper/docs/noise-arms.md` | Give the model a few selected events, never log volume |
| 5 | Mixing 5 incidents: Acc@5 80.0 to 33.0 (Kafka). On-topic noise costs the same as unrelated noise | same | Cut by entity and time window before anything else |
| 6 | 47.7% of runs had a log event, 26.0% a printing site; results flat by report type (66.5 / 66.6 / 70.8) | `c7-coverage-wf-seed42.json`; paper sec. 5.1 | Logs are often silent. Every step must be able to say "nothing" |
| 7 | Missing in the paper: a run without logs, and raw runtime log bundles | paper sec. 6.3 | Our dataset can supply both (section 8) |
| 8 | 57.3% of chain steps cite a log event, 85.7% grounded; the citation comes from the answer form and is checked by code | paper sec. 5.2 | Log evidence goes through the harness's word-for-word check |
| 9 | Dense embeddings lose to text matching for log-to-code on all 27 projects (58.4 to 44.9 Acc@5) | paper sec. 5.5 | Log-to-code stays lexical |
| 10 | Each file gets a role (`cause`, `detects`, `unrelated`); code walks one hop back from `detects` | paper sec. 4 | Each entity gets a role, decided by code (section 6.2) |

### 2.2 Measured here (16-11-2026, `progress-notes/16-11-2026/decisions.md`)

- Free log tools in the old agent: 0 log calls on one run, and on the other the agent blamed
  edge-router, which only complained (front-end was the cause).
- `code_event_loop_block` r1: edge-router logs 458 warnings from 03:59:08; injection at 03:58:46.
  The culprit (front-end) logs nothing new.
- `code_lock_across_io` r1: no log change at all; catalogue `List` p50 is 0.93 ms throughout.
- A healthy Sock Shop run holds 1,449 "payment declined" error lines. Errors present from the
  start are the baseline.
- The OTel agent writes spans to stdout: 321,836 of carts' lines in the sample run, 30 real ones.
- Go services print `caller=file.go:N` and `took=<duration>`; Spring prints `[service,traceId,spanId]`.

### 2.3 Code that exists

| File | State |
|---|---|
| `Blueprint/agent/logtool.py` | Parsing, templates, levels, per-10 s counts, `took=`, log-to-code. Self-test passes. Wired into `agent_v2.py` only, as free tools. Assumes docker log files |
| `Blueprint/eval/nsmap.py` | Container name to pid_ns from CPU totals. Scorer-side: the agent may not import it |
| `Blueprint/eval/make_code_root.py` | Single-bug source tree for `code_*` runs |
| `Blueprint/logkit/` | **Built 25-11 (build steps 1 and 3).** Record, profile loader, `docker_compose` profile, index builder, `log_onset.py`, `log_window.py`; 29 pytest tests, ruff clean. See its README |

### 2.4 A first look at where logs help (probe, 25-11-2026)

One run per fault family, Sock Shop v2 and v3: 37 fault runs and 3 normal runs. Script and
output on Trillium: `work/logs_plan/log_probe.py`, `probe.jsonl`. **A first look, not a result:**
one run per family, the window taken from the label, rough thresholds (errors 3x up, rate 3x
down, p50 3x up and above 5 ms).

| Group | Families | What the logs show |
|---|---|---|
| Clear and fast (13) | `error_storm`, `slow_db`, `conn_pool_exhaustion`, `pid_limit`, `disk_full`, `port_exhaustion`, `dependency_outage`, `svc_mem_cap`, `fd_exhaustion`, `dns_delay`, `db_table_lock`, `net_bandwidth`, `code_lock_contended` | new errors or a latency jump within about 0 to 12 s, in the culprit or its direct caller |
| Victims only, or late (10) | `code_event_loop_block`, `code_serial_awaits`, `svc_cpu_cap`, `slow_client`, `svc_net`, `anomaly_net`, `anomaly_cpu`, `anomaly_mem`, `cpu_weight`, `lock_contention` | other services complain 15 to 120 s later; the culprit is quiet |
| Silent (14) | `noisy_neighbor`, `deadlock`, `fork_storm`, `priority_inversion`, `queue_backlog`, `port_scan`, `svc_cpuset`, `resource_abuse`, `data_exfiltration`, `nagle_delayed_ack`, `anomaly_disk`, `code_lock_across_io`, `code_n_plus_one`, `code_unbounded_cache` | nothing |

Four things from single runs, each to be checked on all runs of the family:

- **Logs can fill a gap the kernel admits.** `dependency_outage` r1: 1,228 `TimeoutException`
  errors in orders (the caller of the frozen service) from +5.2 s. `queue_backlog` r1: nothing.
  Blueprint 15 says the trace cannot tell the two apart.
- **Sometimes the culprit states the reason.** `disk_full` r1: carts-db logs "Failed to write to
  interim file" at +2.0 s, then aborts at +9.0 s.
- **Some faults show as latency only, with no error line.** `db_table_lock` r1: catalogue `List`
  p50 1.2 ms to 965 ms. `net_bandwidth` r1: 1.2 ms to 212 ms. Only services that print a
  duration can show this.
- **Log text can mislead.** `pid_limit` r1 reads `OutOfMemoryError` in orders; a database
  connection failure reads "not found" in catalogue (`error_storm`, `port_exhaustion`).

One false-alarm source: `user` stops logging `Register`, `PostAddress` and `PostCard` in almost
every run, normal ones too. That is the load generator ending its warm-up, not a fault. A
method that stops is not a signal unless it is absent from the normal runs' pattern.

Three kinds of signal were seen, and a tool must report them apart: a new error template, a
latency change, and a drop in a service's line rate (`code_event_loop_block`: front-end 765 to
41 lines/s).

## 3. Design for sources we do not have yet (partner logs)

Partner traces have no logs today. They may come later, and they will not look like ours: no
containers, syslog or journal lines, threads instead of services, a different clock. So nothing
below the parser may assume docker.

### 3.1 One record, any source

Every log line becomes one record:

| Field | Meaning | Sock Shop | A bare-metal host (expected) |
|---|---|---|---|
| `t` | time on the TRACE clock, seconds | docker timestamp (same host clock) | syslog or journal time plus an offset |
| `entity` | who wrote it | container name | process or daemon name (`comm`), or a card or slot id |
| `kind` | what an entity is | `container` | `process`, `thread` or `host` |
| `level` | 0.5 to 4 | from the line | from the syslog priority or the line |
| `msg` | the text | after the docker prefix | after the syslog header |
| `src` | file the line came from | per-container file | one file for the host |

### 3.2 A source profile per log format

A small declared profile, not code branches:

```yaml
# Blueprint/agent/logsources/docker_compose.yaml
id: docker_compose
files: "logs/*.log*"            # may be gzipped
line: '^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z (?P<msg>.*)$'
ts_format: iso_utc
entity: {from: filename, strip: ['^docker-compose[_-]', '[_-]\d+$', '\.log(\.gz)?$']}
kind: container
skip: ['LoggingSpanExporter', '\[scopeInfo:']      # span relay, counted and dropped
latency: '\btook=([\w.µ]+)'
```

A partner profile is a new file of this shape (for example `syslog_rfc3164.yaml`,
`journald_json.yaml`). Adding a source must not touch a tool or a blueprint.

### 3.3 The clock

Tools compare log times with trace times, so one offset per run is part of the index:

- Sock Shop: 0 (same host clock; the audit measured 0.001 ms drift).
- Another source: taken from a declared anchor (a file like our `meta/runinfo_*`), or measured from
  an event both sides record. If neither exists the index says `clock: unknown`, and the tools
  then print times as "log clock" and refuse the window comparison (`LOG CLOCK NOT ALIGNED`)
  instead of guessing. Syslog lines without a year or a time zone are the known trap.

### 3.4 Joining logs to the trace

The kernel names a `pid_ns` (containers) or a thread (`comm`, tid). The log names an entity. The
join is a table in the index, `entity -> trace identity`, with how it was made:

| Host kind | Join | Confidence |
|---|---|---|
| containers | CPU ranking: `meta/cgroup_*` CPU totals per container against CPU time per pid_ns, summed from a scheduling slice the blueprint already cut | the `nsmap` method was measured against the count index (ratio 1.09 to 1.10 on one run); from a slice it is not measured yet |
| bare metal, one namespace | entity name equals the kernel `comm` (cut to 15 characters) | by name |
| no join possible | the tools still work per entity; `log_role` prints `NOT JOINED` | none |

**Correction, 25-11-2026.** The first version of this table used our count index
(`<run>.tsv.gz`). The graph harness does not have it: `bp_graph.py` and the blueprint tools read
only LTTng's own packet index (`index/*.idx`, through `idx_summary.py` and `extract_slice.sh`).
The count index is used only by the old agent (`agent_v2.py`), the scorer (`nsmap.py`) and the
selector scripts. So the join must work from a slice, or the log steps would bring back a
10-minute build per run.

### 3.5 Rules for partner logs

- Local models only. No partner log line, host name or product name in git, in a blueprint, in a
  profile's comments or in a results file. Profiles are named by format, never by owner.
- Sweeps on partner logs stay off git, as for blueprints 0 and 8 to 10.
- A profile for a new format is tested on a synthetic file committed next to it.

## 4. The log index (built once per run, no model)

`<run>.logidx.json.gz`, next to the kernel index. Per entity: line count, lines skipped, first
and last time, templates (text, level, first seen, last seen, count, counts per 10 s, one example
line), latency samples per 10 s where the profile declares one. Plus the profile id, the clock
offset and the join table.

- Built by `build_log_index.py <run_dir> --profile <id>`; nothing but the files the profile names
  is opened. `ground_truth.json` and `verification.*` are never under `logs/`, and the builder
  refuses a profile whose `files` pattern leaves the logs folder.
- Measured cost on the sample run: 250 MB of logs in 7.5 s on a laptop.
- Line ranking keeps INQUEST's rules: earlier errors first, generic timeout / retry lines halved,
  and a template first seen more than 60 s after the run's first line is `new`.

## 5. The tools

Each reads the index, takes no judgment, and prints one verdict line. Bars are named constants.
All three live in one shared folder and are copied into a blueprint's `tools/` like
`extract_slice.sh` is today.

| Tool | Usage | Verdict lines |
|---|---|---|
| `log_onset.py` | `log_onset.py $LOGS` | `LOG ONSET: <entity> (<kind>) first new <level> at HH:MM:SS, N lines; also changed: ...` / `NO LOG CHANGE` / `NO LOGS` |
| `log_window.py` | `log_window.py $LOGS <fault> <secs> --baseline <base> <secs> [--entity E]` | `LOG DIFF: <entity>: K new templates, errors A/s -> B/s, p50 X -> Y ms` per changed entity / `NO LOG DIFF` / `LOG CLOCK NOT ALIGNED` |
| `log_site.py` | `log_site.py $LOGS $CODE <entity> <event id>` | `LOG SITE: <path>:<line> in <function>; callers: ...` / `NO SITE FOUND` |

- `log_window.py` uses the blueprint's own slice and baseline times, so "what changed" means the
  same thing for logs and for the kernel tool.
- `log_onset.py` compares against the start of the run. The agent does not choose that baseline
  (the lesson of the scan tool, `METHOD.md` section 3).
- At most 12 events are printed per call (fact 4).

## 6. Steps in `blueprint.yaml`

The harness gets two new variables, `$LOGS` and `$CODE`, and one new step field, `needs`. A step
with `needs: logs` is skipped with the outcome `no_logs` when the run has none, and the
investigation goes on to that step's `next`. `bp_check.py` learns the field.

### 6.1 `log_orient` (fixed, before `orient`)

```yaml
  log_orient:
    kind: fixed
    needs: logs
    goal: Read where the logs first change. A hint for the time, nothing more.
    run:
      - [log_onset.py, $LOGS]
    extract:
      log_onset_time: 'first new \S+ at (\d\d:\d\d:\d\d)'
      log_first_entity: '^LOG ONSET: (\S+)'
    next: orient
```

`orient` then reads `log_onset_time` next to the rate table. Its text says: the first entity to
complain is often a caller of the faulty one; the check decides, not the log.

### 6.2 `log_role` (fixed, after a confirming outcome)

Runs `log_window.py` at the `fault_start` and `base_start` the kernel steps set. Code then
compares the entity of the kernel verdict (through the join table) with the entities whose logs
changed, and writes the fact `log_role`:

| `log_role` | When | In the report |
|---|---|---|
| `culprit_logs` | the verdict's entity is among those that changed | its lines are quoted as evidence |
| `victims_log` | others changed, the verdict's entity did not | named as victims; the culprit is silent in the logs |
| `silent` | `NO LOG DIFF` | "the logs show nothing" is stated |
| `not_joined` | no join, or the clock is not aligned | the changed entities are listed without a role |

The verdict does not change in any of the four.

### 6.3 `explain` (guided, per blueprint, only after its sweep)

For a blueprint that says "the trace cannot tell". Candidates, each to be confirmed by the sweep:

| Blueprint | The gap in its text | What logs might add |
|---|---|---|
| 15 `dependency_outage` | cannot tell `queue_backlog` from `dependency_outage` | a consumer that logs nothing against a service that logged a stop |
| 22 `error_storm` | "who resets, not why" | the clients' "connection reset" / "link failure" lines; the server's own error |
| 12, 4, 15 behind a refused port | "the service is down or restarting; find out why" | EMFILE, an OOM kill message, a start-up banner |
| 5 `svc_net`, 3 `slow_db` | cannot see inside the path | per-method `took=` on both ends |

Outcomes are matched on the log tool's verdict line, as for kernel tools.

### 6.5 `log_triage`: narrow where to look (proposal, 26-11-2026)

When the agent starts with no blueprint and no suspect, the logs can shorten its search. Two
outputs, both a PRIORITY for the agent, never an exclusion:

1. **A shortlist of services**: the entities whose logs changed, plus the services they CALL. The
   flagged service is usually a caller of the faulty one (it logs the timeouts), so the culprit
   is most often one hop downstream. INQUEST does the same walk at file level ("detects" -> its
   callers). The call graph comes from the run's request traces (`otlp/spans.jsonl`, parent and
   child service names); where there are none (partner hosts), from the kernel's own TCP
   connections (who connects to whom, as `tcp_conns.py` reads them).
2. **Which kinds of fault to check first**, from the symptom class of the flagged lines: refused
   connections or too many open files (an outage, `fd_exhaustion`, a memory kill), latency with no
   error (a slow dependency or path), disk or storage errors (`disk_full`), resets (`error_storm`).
   Silence is a hint too: in the full sweep, 17 of 30 held-out Sock Shop families leave nothing in
   the logs, and they are the resource and scheduling faults the kernel blueprints are built for.
   So silent logs move those blueprints up the list; they do not rule anything out.

Measured on the full sweep (Sock Shop, the 102 fault runs with one target service and something
flagged), with the call graph taken from Sock Shop's wiring, not yet from spans:

| shortlist | culprit inside | size (of ~15 containers) |
|---|---|---|
| services whose logs changed | 44 of 102 | median 2 |
| those, plus the services they call | **98 of 102** | median 6 |

**Measured with each run's own call graph from spans (26-11, `Blueprint/spankit`):** Sock Shop
67 of 102 (median 5 of 15), Train Ticket 21 of 26 (median 6 of 46). Every Sock Shop miss is a
blind spot of the spans (catalogue's database calls and edge-router are not traced), so the
graph needs a second source of edges: the kernel's TCP connections (also the only one on partner
hosts), or peers named in log lines. Details: `Blueprint/logkit/RESULTS.md`.

Not covered: the single-service runs where the logs flag nothing, and the host-level faults.

To evaluate, against a no-log start (every service, every blueprint): culprit inside the
shortlist, shortlist size, and whether the right blueprint is among the first three suggested.

### 6.4 `code_site` (later, code blueprints 17, 23, 24, 25)

INQUEST's examine step: one file per step with the file on screen, a fixed verdict (`cause`,
`detects`, `unrelated`, up to three function names copied from a list), one hop back by code from
`detects`. Not part of the first build. The testbed is small: 10 runs with a runtime effect, and
the 5 defects sit in 2 functions.

## 7. Build order

Follows the seven steps of `METHOD.md`, with "tool" meaning a log tool.

| # | Work | Output | Needs |
|---|---|---|---|
| 1 | Record model, profile loader, `docker_compose` profile, index builder (from `logtool.py`) | `build_log_index.py`, self-test on a synthetic file | laptop |
| 2 | Agent-side join (container to pid_ns) from a scheduling slice | join table; checked against `nsmap.py` on the first-set runs | Trillium, CPU only |
| 3 | `log_onset.py`, `log_window.py` with self-tests | the two tools | laptop |
| 4a | **First set** (section 11, decision 3): both tools on every run of 8 families plus the normal runs. **Done 25-11: 0 false alarms in 62 runs; `logkit/RESULTS.md`** | one line per run; the four numbers of section 8 | Trillium, tools only |
| 4b | **Full sweep**: the same on all labelled runs (v2 both applications, v3), only after 4a is read. **Done 26-11: 363 runs; held-out false alarms 0 on Sock Shop, 2 on Train Ticket; `logkit/RESULTS.md`** | the table of section 8.1 | Trillium, tools only |
| 5 | Read every false alarm and every miss; fix a rule only with the run named; re-sweep | rule history in this folder | - |
| 6 | Add `needs`, `$LOGS`, `log_orient` and `log_role` to the harness and to 3 blueprints chosen by the sweep (expected: 17, 22, 15) | yaml, `bp_check.py` passes | laptop |
| 7 | Agent check on the with-logs arm (section 8.2) | evaluation file | API or cluster; cost stated first |
| 8 | Second profile on a synthetic syslog file, with a clock offset and no join | proves section 3 without partner data | laptop |
| 9 | `log_site.py`, `code_site` | later | - |

Steps 1 to 5 and 8 need no model.

## 8. How it is evaluated

**A log tool is a watchdog, not a judge** (decision 1). No error in the logs does not mean no
fault: 14 of 37 families in the probe are silent. So a log tool is never scored with one
accuracy figure, and its "quiet" is never read as "healthy".

| | Kernel tool | Log tool |
|---|---|---|
| Job | confirms or rejects one fault | watches for any change |
| "Quiet" means | not this fault | unknown |
| Scored on | found, and false alarms | false alarms, coverage, timing and role, added value |

The four numbers, always reported apart:

| Number | Question | Data |
|---|---|---|
| False alarms | does it bark when nothing is wrong? | the normal runs, plus the time before the injection in every fault run (healthy data in every labelled run) |
| Coverage | for which faults do logs show anything? | per family: culprit logs it / only victims log it / silent |
| Quality when it barks | is the time right, is the role right? | seconds from the injection; culprit or victim against the label |
| Added value | does the blueprint do better with it? | the same agent with and without logs (8.2) |

- **Only a false alarm is an error.** A silent family is a blind spot and is listed as one.
- The tool's own line says "the logs show nothing", never "healthy" or "normal".
- The kernel tools are tested as `METHOD.md` section 2 says: one contrast, every run of the
  own family (all found), every other run (all quiet), each false alarm read. The log tools
  follow the same steps; what differs is the score, as in the table above.

### 8.1 The sweep table (tools only)

Per fault family and application:

| Column | Meaning |
|---|---|
| runs | labelled runs swept |
| logs change | runs where `log_window.py` prints a `LOG DIFF` in the injection window |
| onset error | median of (`log_onset_time` minus injection start), seconds; and how many are within 30 s |
| first entity | culprit / caller of the culprit / unrelated |
| culprit logs | runs where the target entity itself changed |
| normal runs | `log_onset.py` on the 20 fault-free runs: how many print `LOG ONSET` |

`fault_catalog.md` holds a pre-registered `expected_winning_modality` per fault. The table is
compared with it and the differences are reported, not edited away.

This table is also the two tests the INQUEST paper lists as missing: logs against no logs, and
raw runtime logs instead of pasted excerpts.

### 8.2 The agent arm

One arm added to `EVALUATION-PLAN.md`: arm A with `$LOGS`, on the same runs and the same frozen
commit as arm A.

| Measure | Question |
|---|---|
| verdict (confirmed / rejected) | must not change: logs do not decide |
| window overlap with the injection | do logs help find the time? |
| slices cut and scan calls before the confirming check | do logs save work? |
| tokens and model calls | what do the log steps cost? |
| `log_role` against the label's target | is the role right? |
| normal runs | no new false alarm |

### 8.3 Pass bars (proposal)

- `log_onset.py` prints `NO LOG CHANGE` on all 20 normal runs, or every exception is read and
  written down.
- A blueprint gets a `log_orient` step only if, on its own family, the onset is within 30 s of
  the injection in at least 4 of 5 runs.
- An `explain` step is added only if the log line separates the two cases on every labelled run
  of both.
- With logs, no verdict of arm A changes. A change is a bug in the harness, not a result.

## 9. Risks

| Risk | Seen where | Handling |
|---|---|---|
| The complainer is blamed | 16-11 pilot (edge-router) | `log_role` is set by code; the report says "victim" |
| Baseline errors read as a fault | 1,449 payment-declined lines | onset needs a NEW template or a rate change against the run's start; normal-run bar |
| Silent faults | `code_lock_across_io`, `port_scan` | `NO LOG CHANGE` is a normal outcome; nothing waits on logs |
| Log volume | span relay, 250 MB runs | profile `skip` list; index built once; 12 events per call |
| Clock not aligned | future sources | `LOG CLOCK NOT ALIGNED`; no window comparison |
| The UST relay stream is empty in most runs (CAMPAIGN-ISSUES 26) | v2, v3 | not used by this plan; the join is by CPU totals, not by the relay |
| Latency only where the service prints it | go-kit: catalogue, user, payment | the column is empty elsewhere; never read as "no latency change" |
| The join is wrong | not yet swept | step 2 checks it on every run before any role is reported |

## 10. Not in this plan

- Incident memory (INQUEST's S4): it needs thousands of past incidents; we have 349 runs. Its
  place here would be the selector, later.
- Embeddings for log matching (fact 9).
- A log-only blueprint. Wait for the sweep to show a fault that only logs see.
- Metrics and request traces. Same shape as this plan if they follow, a separate file.

## 11. Decisions taken (25-11-2026)

1. **A log tool is a watchdog.** It helps to detect a problem and to find its time. No error in
   the logs does not mean there is no fault, so "quiet" means "unknown". (User.)
2. **Scored on four numbers, not one**: false alarms, coverage, quality when it barks, added
   value (section 8). Only a false alarm is an error.
3. **Start small, where logs help** (user), not all 349 runs at once. First set, chosen from the
   probe (section 2.4), every run of each family plus the normal runs:

   | Case | Families | Why |
   |---|---|---|
   | fills a gap the kernel admits | `dependency_outage`, `queue_backlog`, `svc_mem_cap` | caller errors against silence; timeout against connection refused |
   | the culprit explains itself | `disk_full` | the reason is in its own log |
   | latency only | `db_table_lock`, `net_bandwidth` | no error line; tests the duration signal |
   | fast, misleading text | `error_storm` | onset at +0.4 s, the text says "not found" |
   | victims only | `code_event_loop_block` | the culprit is quiet, a caller complains |

   The full sweep (step 4b) follows only after these are read.
4. **Prepared for partner logs** (section 3), though they have none today. (User.)
5. **Logs never change a kernel verdict** (section 1).
6. **No count index in the log path.** The join is computed from a slice (section 3.4).
7. **Logs also narrow WHERE to look** (user, 26-11): a shortlist of services and the kinds of fault
   to try first, when the agent does not know where to start (section 6.5). Priority, never
   exclusion.

## 12. Still open

1. The pass bars of section 8.3 (proposal: quiet on every normal run; a time hint only where
   the onset is right in at least 4 of 5 runs of the family).
2. The window for "onset is right": 30 s is a proposal. The probe saw 0 to 12 s in the clear
   group, so 30 s may be loose.
3. Whether a line-rate drop is a signal of its own or only a note. First set (25-11): in
   entities logging at least 20 lines/s, a drop came 4 to 5 s after the injection in all 5
   `code_event_loop_block` runs (the first error 22 to 63 s after it), never before an
   injection and never on a normal run. **Decided 26-11: stays a NOTE.** On all 10 healthy
   Train Ticket runs a busy service drops when a load phase ends (`logkit/RESULTS.md`).
4. `log_window`'s baseline (found 26-11 on held-out Train Ticket runs): a 20 s baseline misses a
   warning that comes every 30 s and reports a false rise. Fix proposed in `logkit/RESULTS.md`;
   applying it needs runs it was not set on.
