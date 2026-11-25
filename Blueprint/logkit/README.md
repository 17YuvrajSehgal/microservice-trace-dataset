# logkit

Application logs as a witness for the kernel blueprints. The design and the decisions are in
[`../latency/LOGS-PLAN.md`](../latency/LOGS-PLAN.md); this file says how the code is laid out
and how to run it.

**The rule:** a log tool proposes a time and says which services changed. It never confirms or
rejects a fault, and "no change in the logs" never means "healthy". The kernel check decides.

## Layout

```
logkit/
  record.py          LogRecord: one line from any source (time, entity, kind, msg, src)
  profile.py         SourceProfile: how one log FORMAT is read; refuses ground-truth paths
  profiles/          one YAML file per format (docker_compose.yaml today)
  templating.py      template(), level(), is_generic(), is_frame()  (ported from INQUEST)
  index.py           build_index(): read a run once, keep templates, rates and latency
  build.py           CLI: python -m logkit.build
  tools/             blueprint tools, STANDARD LIBRARY ONLY
    logidx.py        the index format and its reader (the one place the format is defined)
    logsig.py        what counts as a change between two windows (used by both tools)
    log_onset.py     when did the logs first change, and where
    log_window.py    what changed between a baseline slice and a fault slice
  tests/             pytest, on synthetic runs with a known fault and a healthy twin
```

Why `tools/` has no dependencies: the harness copies a blueprint's tools into its `tools/`
folder and runs them with a bare `python3`, as it does `extract_slice.sh`. Copy all four
files together. Building an index needs PyYAML (the cluster venv has it).

## Run it

```bash
cd Blueprint
python -m logkit.build <run_dir> --out-dir <dir>               # -> <dir>/<run_id>.logidx.json.gz
python logkit/tools/log_onset.py <dir>/<run_id>.logidx.json.gz
python logkit/tools/log_window.py <idx> 15:20:30 20 --baseline 15:19:00 20
python -m pytest logkit/tests                                    # 29 tests, under a second
ruff check logkit
```

`build.py` never writes into a run directory, and skips a run whose index exists (`--force`
rebuilds), so a sweep can be resumed.

## Verdict lines

| Tool | Lines |
|---|---|
| `log_onset.py` | `LOG ONSET:` · `NO LOG CHANGE:` · `LOGS TOO SHORT:` · `NO LOGS:` |
| `log_window.py` | `LOG DIFF:` (one per changed entity) · `NO LOG DIFF:` · `LOG WINDOW OUTSIDE LOGS:` · `LOG CLOCK NOT ALIGNED:` · `NO LOGS:` |

A change is one of: a new warning-or-worse template, a rise in the SHARE of warning lines, a
rise in a method's median request time. A fall in the line rate is printed as a `NOTE` only
(open decision, LOGS-PLAN.md section 12). The bars are named constants at the top of
`tools/logsig.py` and `tools/log_onset.py`.

## Adding a log source

Write `profiles/<format>.yaml` (fields in `profile.py`'s docstring) and a test with a small
synthetic file of that format. No tool changes. A source whose clock cannot be matched to the
trace sets `clock: {status: unknown}`; `log_window.py` then refuses with `LOG CLOCK NOT ALIGNED`
instead of guessing. Partner logs: local models only, and no partner name, host or log line in
a profile, a test or this repository.

## Known limits

- Windowed signals (warnings, latency) are found to within one 10 s window.
- Latency exists only where a service prints its own duration (go-kit `took=`: catalogue,
  user, payment). Elsewhere the column is empty, which is not "no latency change".
- `Blueprint/agent/logtool.py` (the old agent's copy) still has its own parser. This package is
  the one to change.
