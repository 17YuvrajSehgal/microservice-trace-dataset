# Collection-rig troubleshooting (hard-won, 2026-07-28)

Every issue below cost real time during the first VM bring-up. Most are now
fixed at the source (in the scripts/overlays); the rest have a one-line fix
here. **If you are provisioning a fresh VM, run `vm_bootstrap.sh` then
`run_gate.sh gate01` — the fixes are already baked in and a clean gate should
take minutes, not hours.**

## Symptom → cause → fix

### `lttng destroy` / any collect run hangs forever; SSH shows "exit 128"
**The big one.** An interrupted run (SSH drop mid-collection) leaks an LTTng
session and wedges the consumer daemon. A subsequent plain `lttng destroy`
then BLOCKS FOREVER waiting for the consumer to flush; over SSH this looks
like a network "exit 128" but it is a local hang.
- **Fixed at source:** `collect_trace.sh` runs a bounded pre-flight
  (`timeout 10 lttng destroy`; force-kills daemons if it wedges).
- **If already wedged and even that hangs:** the only reliable clear is a
  hypervisor hard reset: `gcloud compute instances reset <vm> --zone <z>`.
  A soft `reboot` can be blocked by the wedged processes and NOT reboot
  (check `uptime` after). The Docker stack auto-restarts on boot.
- Never SIGKILL-loop the daemons over SSH; if they are stuck in kernel I/O a
  reset is faster than fighting them.

### `metrics EMPTY` in the audit / `curl: (7) Failed to connect port 9090`
Prometheus has **no restart policy** in upstream's monitoring compose, so it
stays down after a host reboot and silently scrapes nothing.
- **Fixed at source:** `docker-compose.metrics.yml` now sets
  `restart: unless-stopped` on prometheus.
- **On an already-running stack:** `sudo docker start prometheus`.
- `run_gate.sh` warns up front if 9090 is unreachable.
- NOTE: metrics for a window when Prometheus was down are gone for good —
  re-run the scenario, do not just re-export.

### `edge-router` has no published ports; front-end unreachable on :80
Happens if the FIRST `docker compose up` failed partway (e.g. a port clash),
leaving edge-router half-created; a later `up` does not fully recreate it.
- **Fix:** `docker compose ... up -d --force-recreate edge-router`.
- The port clash that caused it (cAdvisor vs edge-router on 8080) is
  **fixed at source** (cAdvisor host port is 8081 in
  `docker-compose.metrics.yml`), so a clean first `up` no longer trips this.

### `kernel SKIPPED (0 events)` in the audit
Three distinct causes were hit; all fixed:
1. Root-owned CTF — `collect_trace.sh` now chowns the bundle to the user.
2. Invalid `--clock-gmt` (a babeltrace v1 flag) silently aborted bt2 — the
   audit now uses the correct bt2 trimmer `--begin/--end`.
3. The event regex could not skip the hostname token in the bt2 line
   (`[ts] (+delta) <hostname> <event>: {...}`) — re-anchored on the event
   name. If you see 0 events with a readable CTF, run the audit's bt2 line
   manually and check the output format matches the regex.

### Docker group not active in the shell (`permission denied` on docker.sock)
After `usermod -aG docker`, the current shell does not have the group yet.
- **Fix:** `newgrp docker`, or log out/in. Scripts that must work in the
  same session wrap docker calls in `sg docker -c "..."`.

### Load generator writes nothing / `can't open load_generator.py`
Shell backgrounding trap: `cd DIR && ... & rest` backgrounds the whole
`&&`-chain, so `rest` runs from the ORIGINAL cwd. Use absolute paths (as
`run_gate.sh` does) or put the whole job in a script.

## Operational notes
- `otlp-out/spans.jsonl` (collector's global span file) is truncated after
  each run's slice by `collect_trace.sh`, so it no longer grows unbounded.
- Driving the VM from a laptop/CI over `gcloud compute ssh`: long inline
  commands drop the channel. Pattern that works — write a script, launch with
  `nohup ... & disown`, poll a result file with short commands.
- All performance/overhead numbers must come from the VM, never a laptop/WSL.
