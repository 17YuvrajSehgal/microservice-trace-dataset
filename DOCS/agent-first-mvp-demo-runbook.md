# Demo runbook — agent-first, collection-aware observability

**Thesis in one line.** A *skill* compiles a plain-language problem ("my database is
slow") into a scoped, machine-readable **collection spec**, then runs a **kernel-deep**
RCA over four modalities and returns a clean verdict — deciding *what to collect* from the
problem, differently for every problem. No incumbent (Datadog, Dynatrace) or academic
system (TMLL, HolmesGPT) does this.

Everything runs on the GCP VM `stratatrace-collector` (us-east1-d). All analysis is
**read-only** on the 164 GB dataset (`~/traces`); working copies live in `~/mvp_work/`,
live captures in `~/mvp_captures/`.

---

## 0. One-time setup (already done; re-check before the demo)
```bash
gcloud compute instances start stratatrace-collector --zone=us-east1-d
gcloud compute ssh stratatrace-collector --zone=us-east1-d
cd ~/microservice-trace-dataset && git checkout agentic-tracing && git pull
docker ps | wc -l            # expect ~19 Sock Shop containers up
python3 -c "import fastmcp"   # MCP server dep (else: python3 -m pip install --break-system-packages fastmcp)
ls ~/mvp_work/results/*.html  # pre-cached dashboards + index.html
```

## The 4-act demo

### Act 1 — the agent decides *what to collect* (the differentiator)
Show that one sentence produces a **scoped** plan, not "collect everything".
```bash
cd ~/microservice-trace-dataset/agent-first-mvp
python3 demo_cli.py discover "my catalogue database is really slow"
python3 demo_cli.py phase1 db-slowness-rca      # <- SHOW THIS: only 3 sched events + 6 syscalls
```
**Say:** "It picked the db-slowness skill and emitted a collection spec — only these kernel
events on only these two services, for 60 s, with the exact `lttng` command. That scoping
is the novel unit."

### Act 2 — kernel-deep verdict (replay, guaranteed)
```bash
python3 demo_cli.py run db-slowness-rca          # ~1–2 min (pre-cache before stage)
```
**Say:** "The kernel wait-attribution says catalogue spends 99% off-CPU on I/O wait, 0.7%
on-CPU, 0% disk — so it rules out CPU-bound and disk-bound, and the DB engine itself is
healthy. Root cause: the DB *connection path*. It matched the hidden ground truth, and it
read ~30× less data than an undirected kernel-deep pass." Open `results/db-slowness-rca.html`.

### Act 3 — different problem → different decisive modality (breadth)
Open `results/index.html` (the benchmark). Four problems, four **different** decisive
modalities, all correct vs ground truth:
| problem | decisive modality |
|---|---|
| database is slow | kernel + traces |
| everything's a bit slow | **kernel-only** (names the stress-ng neighbor; service KPIs flat) |
| orders are failing | **traces + kernel** (payment frozen: 0 spans, callers hang at 5 s) |
| tons of 500s | **logs + metrics** (5xx 0→229/s + reset signatures) |

**Say:** "Same engine. The system decided to collect something different each time — and a
different modality was decisive each time. The noisy-neighbor case is the punchline: metrics
and traces see nothing wrong; only the kernel names the culprit."

### Act 4 — live, scoped capture (the wow; replay is the fallback)
```bash
python3 demo_cli.py run db-slowness-rca --live    # creates a scoped LTTng session, injects live, analyzes
```
**Say:** "That LTTng session recorded ONLY the events the skill declared — collection-
awareness, live — injected the fault under load, captured a short window, restored it, and
produced the same verdict from fresh data."

### Optional — the agent drives it (MCP)
```bash
# from Claude Code with agent-first-mvp/.mcp.json loaded:
#   "my database is slow" -> Claude calls discover_skills -> phase1_requirements -> run_skill
python3 mcp_server.py    # stdio server exposing the tools
```

---

## Fallback ladder (if something misbehaves live)
1. **Live capture flakes** → drop `--live`; replay is identical and pre-cached.
2. **`run` too slow on stage** → open the pre-cached `results/*.html` (already generated).
3. **MCP/agent hiccup** → `demo_cli.py` runs the exact same loop deterministically.
4. **VM issue** → the hero dashboard is also published as a claude.ai Artifact (shareable).

## Honesty notes (what NOT to overclaim)
- The verdict is **deterministic** (rule-scored over structured evidence); the LLM only
  narrates. Say that — it's a strength.
- "Kernel-deep" here = per-thread wait-attribution + cgroup silence + process naming from
  LTTng syscalls/sched. Not eBPF continuous profiling.
- The data-reduction number is *processing* cost (scoped bytes vs full decompressed kernel +
  spans/logs for that run), not a storage claim.
- 4 faults are wired deep; the 5th skill (cpu-saturation) is in the catalog, not yet wired.

## Reset / cleanup
```bash
lttng destroy -a 2>/dev/null; sudo lttng destroy -a 2>/dev/null   # if a live session lingers
cd ~/microservice-trace-dataset/microservice-lttng-data-collection-scripts/faults
./slow_db.sh cleanup   # if a fault wasn't restored
# Stop the VM when done (it costs money):
# gcloud compute instances stop stratatrace-collector --zone=us-east1-d
```
