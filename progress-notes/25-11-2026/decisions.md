
## RCA Studio: demo data restored, simpler tree, data sources

- **The WSL data folder was deleted on 18-11** (disk cleanup in another session), so the
  partner traces, links and runs were gone from the UI. Restored from: the original archives
  (extracted, not read), the link map found in the 04-11 session log, and the final-pass
  verdicts in the local, git-ignored results folder. The copy on Trillium is the first pass
  only (before the blueprint fixes), so it must not be used for demos.
- **Tree**: runs are listed only under their trace; a run row starts with its blueprint.
  Why: every run was shown twice and rows under one trace looked the same.
- **Run panel** opens as a tab in the active editor group, not a new column per run.
- **Data sources** (logs, metrics, distributed traces) can be connected to a trace. One
  record shape (time, source, text, fields) and a registry of types, so a new backend is one
  class and the extension does not change (it builds its form from the server's field list).
  Why this shape: we do not know the partner's log / metric systems yet. Built-in types only
  read our dataset's files. Not done: the agent does not use these sources yet; they are for
  viewing. Queries read files from the start (logs 2-4 s, 768 MB of spans up to 10 s).
