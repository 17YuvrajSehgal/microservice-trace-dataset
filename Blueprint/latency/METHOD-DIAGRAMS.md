# How a `blueprint.yaml` is made and used (diagrams)

Companion to `METHOD.md`. Written 25-11-2026 for the supervisor meeting.

## 1. From tool to agent run

```mermaid
flowchart TD
    A[Tool written and tested<br/>prints one VERDICT line] --> B[Sweeps on all labelled runs<br/>numbers saved in RESULTS.md]
    B --> C[Fill blueprint.yaml<br/>16 required fields]
    C --> D{bp_check.py}
    D -- "ERROR: missing field, broken step link,<br/>script not in tools/,<br/>verdict line no tool prints" --> C
    D -- "WARN: a number with no source" --> E[Look at the number<br/>fix it or find its source]
    E --> C
    D -- ok --> F[bp_render.py]
    D -- ok --> G[bp_graph.py harness]
    F --> H[BLUEPRINT.md<br/>for people, never edited by hand]
    G --> I[Agent runs one step at a time<br/>on a labelled trace]
    I --> J[Answer per run<br/>plus a log of every time<br/>the agent left the guidance]
    J -- "wrong answer traced to a step" --> K[Change the text of that step<br/>tool and bars stay the same]
    K --> C
```

The yaml file sits in the middle. Everything before it produces checked numbers. Everything
after it is generated from it, so the text and the agent's steps cannot differ.

## 2. The steps inside one file (blueprint 22, `error_storm`)

```mermaid
flowchart TD
    S([start]) --> A["check_trace (fixed)<br/>harness runs idx_summary.py<br/>reads date, start, end"]
    A --> B["orient (guided)<br/>agent picks a fault time<br/>and a baseline time"]
    B -- times_chosen --> C
    B -- no_window --> C
    C["connections (guided)<br/>agent cuts two slices<br/>runs tcp_conns.py"]
    C -- "reset_storm<br/>VERDICT: SERVER ACCEPTS AND THEN RESETS" --> R([report: confirmed])
    C -- "refused<br/>VERDICT: SERVER PORT REFUSES" --> X1([stop: service is down,<br/>go to blueprint 4, 12 or 15])
    C -- "new_holder<br/>VERDICT: NEW CLIENT HOLDS CONNECTIONS" --> X2([stop: go to blueprint 6])
    C -- "no_storm<br/>VERDICT: NO RESET STORM" --> X3([stop: not this fault])
```

A `fixed` step needs no model. A `guided` step lets the agent choose commands, but it must end
in one of the listed outcomes, and each outcome is tied to an exact verdict line that a tool
prints. (The file has a fifth outcome, `held_no_baseline`, left out here to keep the picture small.)
