# Plan for the logs component

Status: **proposal, 25-11-2026. Nothing in sections 4 to 9 is built or run.** What exists today
is listed in section 2. The pass bars in section 8 are proposals and must be agreed before the
sweep starts; after that they change only with a dated note at the end of this file.

Read with: `METHOD.md` (how a blueprint is built), `EVALUATION-PLAN.md` (arms and splits),
`Blueprint/agent/bp_graph.py` (the harness).

## 1. Goal, and the one rule

Add application logs to the blueprints so that an investigation can:

1. find the time of a fault faster,
2. say more than the kernel can ("who resets" becomes "who resets, and what it logged"),
3. point at the code that printed a message, where the source is connected.

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
| containers | agent-side copy of the `nsmap` method: `meta/cgroup_*` CPU totals against the index's per-namespace CPU | measured (ratio 1.09 to 1.10 on one run; must be swept) |
| bare metal, one namespace | entity name equals the kernel `comm` (cut to 15 characters) | by name |
| no join possible | the tools still work per entity; `log_role` prints `NOT JOINED` | none |

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
| 2 | Agent-side join (container to pid_ns) | join table in the index; checked against `nsmap.py` on every Sock Shop run | Trillium, CPU only |
| 3 | `log_onset.py`, `log_window.py` with self-tests | the two tools | laptop |
| 4 | **Sweep**: both tools on all 349 runs (v2 both applications, v3), times from the label for `log_window.py`, no label for `log_onset.py` | one line per run; the table of section 8.1 | Trillium, tools only |
| 5 | Read every false alarm and every miss; fix a rule only with the run named; re-sweep | rule history in this folder | - |
| 6 | Add `needs`, `$LOGS`, `log_orient` and `log_role` to the harness and to 3 blueprints chosen by the sweep (expected: 17, 22, 15) | yaml, `bp_check.py` passes | laptop |
| 7 | Agent check on the with-logs arm (section 8.2) | evaluation file | API or cluster; cost stated first |
| 8 | Second profile on a synthetic syslog file, with a clock offset and no join | proves section 3 without partner data | laptop |
| 9 | `log_site.py`, `code_site` | later | - |

Steps 1 to 5 and 8 need no model.

## 8. How it is evaluated

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

## 11. Decisions needed before step 4

1. The pass bars of section 8.3.
2. Whether v3 runs are in the sweep from the start (they are in the 349) or added after v2.
3. The window for "onset is right": 30 s is a proposal.
