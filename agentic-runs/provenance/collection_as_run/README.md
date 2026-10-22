# Collection scripts — agentic OS-noise experiment

What these collect and why: see `../PLAN.md`. Structure mirrors
`../../../microservice-lttng-data-collection-scripts` (per-run collector, campaign
driver, manifest, ground truth per run).

## Files

| file | what |
|---|---|
| `vm_setup_agentic.sh` | one-time VM setup: LTTng 2.15 + smoke trace. Agent sign-in is manual, after this |
| `collect_agent_run.sh` | ONE run: fresh task repo → cgroup with `cpu.max` → LTTng (curated v2 kernel profile) → headless `claude -p` → anchors, `cpu.stat`, ground truth |
| `run_campaign.sh` | the grid: tasks × 4 caps × N reps, shuffled, resumable (skips existing run dirs), writes `manifest.csv` |
| `tasks/t1_toy.sh` | ~10 s one-bug task — plumbing checks only |
| `tasks/t2_medium.sh` | 2–5 min three-bug task; its test suite burns real CPU per invocation (throttleable local work) |

## Deploy to the VM

```bash
gcloud compute scp --recurse collection aylabsltd@agentic-noise:collection \
  --project=teleeporter --zone=us-east1-d
# strip Windows line endings once after copying:
gcloud compute ssh aylabsltd@agentic-noise --project=teleeporter --zone=us-east1-d \
  --command="find collection -type f -exec sed -i 's/\r$//' {} +"
```

## Run

```bash
# single run:
bash collection/collect_agent_run.sh t2_cap50_r1 "50000 100000" t2_medium.sh

# full campaign (4 caps x 5 reps of t2_medium = 20 runs):
bash collection/run_campaign.sh 5
```

Output lands in `~/runs/<run>/`: `trace/` (CTF), `agent.log`,
`meta/{ground_truth.json, cpu.stat.before/after, clock_anchors.jsonl,
root.pid, lttng_enabled.txt, task_check.txt}`, plus `manifest.csv` at the
top level.

## Known gotchas (do not rediscover)

- cgroup-v2 delegation: a non-root process cannot move its own PID into
  `/sys/fs/cgroup/agent` — the collector writes `cgroup.procs` via sudo.
- The agent runs in a subshell placed into the cgroup; the parent stays
  outside so lttng/sudo teardown is not charged to the agent's `cpu.stat`.
- LTTng's consumer writes the trace dir as root — the collector chowns it
  back at the end.
- `tcp_*` events fire only on anomalies (retransmit, state change) on this
  kernel; API round-trips show up as `net_dev_xmit` / `net_if_receive_skb`.
- Claude Code must be signed in for the user running the scripts
  (`~/.claude*`); `claude -p` fails without it.
