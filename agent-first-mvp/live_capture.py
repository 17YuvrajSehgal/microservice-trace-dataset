#!/usr/bin/env python3
"""MODE A — live, scoped kernel capture driven by a skill's collection spec.

This is the collection-aware thesis, live: the skill declares exactly which kernel
events/syscalls to record, we create an LTTng session that captures ONLY those,
inject the matching fault (reusing the tested faults/ recipes) under load, capture a
short window, then hand the fresh run to the same phase-2 engine for a verdict.

Writes ONLY to ~/mvp_captures/ (never ~/traces — the dataset stays read-only).
Robust cleanup: the LTTng session is destroyed and the fault restored in `finally`,
even on error/interrupt. Reuses collect_trace.sh's preflight idea to unwedge stale
consumer daemons. Run on the VM (needs sudo for the kernel session, Docker for load).

    python3 live_capture.py --skill db-slowness-rca            # full live loop
    (or via) python3 demo_cli.py run db-slowness-rca --live
"""
import argparse, json, os, shutil, subprocess, sys, time, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "microservice-lttng-data-collection-scripts")
CAPROOT = os.path.expanduser("~/mvp_captures")
FAULT_RECIPE = {  # fault_source -> (recipe script, intensity, target services for spans/logs)
    "slow_db": ("slow_db.sh", "aggressive"),
    "noisy_neighbor": ("noisy_neighbor.sh", "aggressive"),
    "dependency_outage": ("dependency_outage.sh", "aggressive"),
    "error_storm": ("error_storm.sh", "aggressive"),
    "anomaly_cpu": ("anomaly_cpu.sh", "aggressive"),
}

def _utc(): return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)
def log(m): print(f"  [live] {m}", flush=True)

def preflight():
    sh("timeout 10 lttng destroy -a"); sh("sudo timeout 10 lttng destroy -a")

def build_enable(spec):
    """Translate the skill's kernel spec into scoped `lttng enable-event` commands.
    THIS is the collection-awareness: only declared events get recorded."""
    k = spec["collection_spec"]["kernel"]
    syscalls = ",".join(k.get("syscalls") or [])
    events = ",".join(k.get("events") or [])
    cmds = []
    if syscalls: cmds.append(f"sudo lttng enable-event -k --syscall {syscalls} --channel channel0")
    if events:   cmds.append(f"sudo lttng enable-event -k {events} --channel channel0")
    return cmds, syscalls, events

def slice_bytes(src, out, off0):
    """Copy the bytes appended to `src` since offset off0 into `out` (the run's window)."""
    try:
        size = os.path.getsize(src)
        with open(src, "rb") as f:
            f.seek(off0); data = f.read(max(0, size - off0))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as g: g.write(data)
        return len(data)
    except OSError:
        return 0

def capture(skill, baseline_s=12, injection_s=35, users=8, drain_s=10):
    """Run the live loop for a skill dict. Returns (run_dir, kernel_dir) for phase2."""
    import importlib.util
    sys.path.insert(0, os.path.join(HERE, "engine"))
    import phase2
    spec = phase2.phase1(skill)
    fs = skill["fault_source"]
    recipe, intensity = FAULT_RECIPE.get(fs, (None, "aggressive"))
    run_dir = os.path.join(CAPROOT, f"{skill['skill']}_live")
    kernel_dir = os.path.join(run_dir, "kernel", "kernel")
    if os.path.exists(run_dir): shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(kernel_dir, exist_ok=True); os.makedirs(os.path.join(run_dir, "meta"), exist_ok=True)
    otlp_src = os.path.join(SCRIPTS, "otlp-out", "spans.jsonl")
    off0 = os.path.getsize(otlp_src) if os.path.exists(otlp_src) else 0

    fault_injected = False; load = None
    try:
        preflight()
        log("creating SCOPED kernel session (only the skill's declared events)…")
        assert sh(f"sudo lttng create sockshop-live --output={run_dir}/kernel").returncode == 0, "lttng create failed"
        enable_cmds, sysc, evs = build_enable(spec)
        for c in enable_cmds:
            r = sh(c)
            if r.returncode != 0: log(f"warn: {c.split('--syscall')[0][:30]}… {r.stderr.strip()[:80]}")
        sh("sudo lttng add-context --kernel --channel channel0 --type=pid --type=tid --type=procname")
        log(f"scope → syscalls[{sysc}] events[{evs}]")
        sh("sudo lttng start")
        # capture the container main PIDs now (for TGID identity), like docker-top snapshots
        _snapshot_tops(run_dir, spec)

        begin = _utc()
        log(f"load: {users} users on the live stack; baseline {baseline_s}s…")
        load = subprocess.Popen([sys.executable, os.path.join(SCRIPTS, "load_generator.py"),
                                 "--host", "http://localhost:30001", "--users", str(users),
                                 "--duration", str(baseline_s + injection_s + 5),
                                 "--output", os.path.join(run_dir, "load.csv")],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(baseline_s)
        inj_start = _utc()
        if recipe:
            log(f"INJECT {fs} ({intensity}) …")
            r = sh(f"cd {SCRIPTS}/faults && ./{recipe} inject {intensity}")
            fault_injected = (r.returncode == 0)
            if not fault_injected: log(f"inject rc={r.returncode}: {r.stderr.strip()[:120]}")
        time.sleep(injection_s)
        inj_end = _utc()
        if fault_injected:
            log("restore fault…"); sh(f"cd {SCRIPTS}/faults && ./{recipe} cleanup"); fault_injected = False
        end = _utc()
    finally:
        log("stop + destroy kernel session (cleanup)…")
        sh("sudo lttng stop"); sh("sudo lttng destroy")
        # the session is root-owned (sudo lttng); hand it back so babeltrace2 (our uid) can read it
        sh(f"sudo chown -R $(id -u):$(id -g) {run_dir}/kernel")
        if fault_injected:
            sh(f"cd {SCRIPTS}/faults && ./{recipe} cleanup")
        if load and load.poll() is None:
            load.terminate()
            try: load.wait(5)
            except Exception: load.kill()

    log(f"draining {drain_s}s so the OTel collector flushes the window's spans…")
    time.sleep(drain_s)  # collector batches spans; too short => catalogue spans missed
    nb = slice_bytes(otlp_src, os.path.join(run_dir, "otlp", "spans.jsonl"), off0)
    log(f"sliced {nb/1e6:.1f} MB of spans for the window")
    _dump_logs(run_dir, spec, begin)
    gt = {"fault": {"name": f"{fs}_live", "target_service": skill.get("requirements",{})
                    .get("kernel_lttng",{}).get("scope",{}).get("target_services",["?"])[0],
                    "parameters": {"intensity": intensity, "note": "injected live by live_capture.py"},
                    "injection_start_utc": inj_start, "injection_end_utc": inj_end,
                    "target_trace_visibility": "live"},
          "remediation": {"action": f"restore via faults/{recipe} cleanup"}}
    json.dump(gt, open(os.path.join(run_dir, "ground_truth.json"), "w"), indent=2)
    log(f"live run ready → {run_dir}")
    return run_dir, kernel_dir

def _snapshot_tops(run_dir, spec):
    """docker-top the scoped services so the engine can resolve container main PIDs (TGID)."""
    svcs = (spec["collection_spec"]["kernel"].get("scope", {}) or {}).get("target_services", [])
    meta = os.path.join(run_dir, "meta")
    for s in svcs:
        cont = f"docker-compose_{s}_1"
        r = sh(f"docker top {cont} -eo pid,tid,ppid,psr,stat,comm,args")
        if r.returncode == 0 and r.stdout.strip():   # name must match engine main_pid glob
            open(os.path.join(meta, f"top_{cont}_start.txt"), "w").write(r.stdout)

def _dump_logs(run_dir, spec, since):
    logs = os.path.join(run_dir, "logs"); os.makedirs(logs, exist_ok=True)
    svcs = set((spec["collection_spec"].get("logs", {}) or {}).get("services", []))
    svcs |= set((spec["collection_spec"]["kernel"].get("scope", {}) or {}).get("target_services", []))
    for s in svcs:
        cont = f"docker-compose_{s}_1"
        r = sh(f"docker logs --since {since} {cont}")
        if r.returncode == 0:
            open(os.path.join(logs, f"{cont}.log"), "w", errors="replace").write(r.stdout + r.stderr)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--baseline-s", type=int, default=12)
    ap.add_argument("--injection-s", type=int, default=35)
    ap.add_argument("--users", type=int, default=8)
    a = ap.parse_args()
    sk = json.load(open(os.path.join(HERE, "skills", a.skill, "skill.json")))
    rd, kd = capture(sk, a.baseline_s, a.injection_s, a.users)
    print(json.dumps({"run_dir": rd, "kernel_dir": kd}))
