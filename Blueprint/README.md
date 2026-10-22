# Blueprint — the active workspace

This folder is where current work happens. It is built to stand alone: nothing
inside it depends on files outside it, so it can be lifted into its own repo
when the work is ready for the paper.

**The older `blueprints/` folder at the repo root is the previous generation.**
It stays as reference (its results and skills are history we cite), but new
blueprints, new tools, and agent work all happen here.

## Map

| Folder | What |
|---|---|
| `000`–`005-*` | Short teaching notes: telemetry, tracing, LTTng |
| `latency/1_svc_cpu_cap/` | The first blueprint: find a CPU cap from a kernel trace. `README_v1.md` is the blueprint; `tools/` are its eight scripts; `EVALUATION-on-agentic-runs.md` is its test against real agentic faults (40/40 detected, 0 false alarms) |
| `../agentic-runs/1_svc_cpu_cap/agentic-os-noise/` | The OS-noise study: collection + analysis + runs for the workshop paper |
| `latency/2–4_*` | The other three mechanism studies (threads, memory, disk I/O) |
| `agent/` | **The kernel-trace RCA agent** — `agent_v2.py` + its support module `utils.py` and tools. Takes a run directory; no data-layer dependency. Distilled from `agentic-rca/` (which keeps the v1 agent, campaign machinery, old skills). See its README |

## Direction

1. Write blueprints as self-contained folders: the blueprint text, its tools,
   and its evaluation evidence side by side (`latency/1_svc_cpu_cap/` is the
   template).
2. Teach `agent/` to use the blueprint tools (`latency/*/tools/`) as its
   investigation toolkit, instead of only its built-in CTF tools.
3. When a piece is 100% ready, it graduates to its own repo for the paper
   (the OS-noise study already has one: `os-noise-for-agentic-ai`).
