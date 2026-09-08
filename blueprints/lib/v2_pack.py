#!/usr/bin/env python3
"""Build ONE complete evidence pack for a v2 run - everything all seven blueprints read.

KERNEL TRACES ONLY. Every measurement below comes from the LTTng kernel trace and nothing
else, which is the scope the 2 Sept meeting set. No spans, no logs, no metrics. Call-graph
convergence is deliberately omitted: it needs OTLP spans, and no blueprint's FIRE decision
uses it.

    ctf_extract      decode the trace ONCE into per-family event files
      oncpu_share        host utilisation, who gained and lost CPU
      runqueue_delay     per-wakeup wait for a CPU
      blocking_syscall   time inside each syscall
      net_loss_signature retransmission and where packets are dropped
      endpoint_latency   request-to-response gap per flow
      block_io_signature disk arrivals, queue depth, device service time
      futex_irq_probe    hard/soft interrupt time and futex waits

WHY ONE EXTRACTION AND NOT SEVEN DECODES
----------------------------------------
Measured (ctf_stream.py): a full decode of one L0 trace is 361 s, and text formatting is 72%
of that. Seven scripts each opening their own babeltrace over the same 115 s of trace is
~26 min per run. Extracting once and letting all seven read the result is ~7 min. Over 136
runs that is the difference between two hours and eight.

The cache holds a family superset and each script's own grep still runs on top, so no script
sees one line more or fewer than it would have. That is what makes it safe.

    python3 v2_pack.py --app sockshop --family slow_db --run slow_db_..._r1 --out <pack_dir>

The cache goes to --cache (default $SLURM_TMPDIR, which is node-local and disappears with the
job) and is deleted after the run either way - it is several GB and there are 136 of them.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)                                    # blueprints/
V2 = os.environ.get("V2_ROOT", "/scratch/yuvraj17/stratatrace/data/stratatrace-v2")

EXTRACT = f"{HERE}/ctf_extract.py"
SYNTH = f"{HERE}/synthesize_gt.py"

# name -> (script, extra args). Order is only for reporting; all are independent.
STEPS = [
    ("oncpu", f"{BP}/problems/cpu-contention-co-tenant/scripts/oncpu_share.py", []),
    ("runqueue", f"{BP}/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py", []),
    ("blocking", f"{BP}/problems/db-latency-dependency-wait/scripts/blocking_syscall.py", []),
    ("netloss", f"{BP}/problems/network-path-degradation/scripts/net_loss_signature.py", []),
    ("endpoints", f"{HERE}/endpoint_latency.py", []),
    ("blockio", f"{BP}/problems/host-disk-saturation/scripts/block_io_signature.py", []),
    ("irq", f"{HERE}/futex_irq_probe.py", []),
]

# Train Ticket reports every Java service as `java`, so that one comm covers ~39 services;
# the datastore stays distinguishable as `mysqld`.
COMMS = {"sockshop": "mysqld,app,node,java",
         "trainticket": "mysqld,java,node,redis-server"}


def run(cmd, env, log):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    with open(log, "a") as fh:
        fh.write(f"$ {' '.join(cmd)}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}\n")
    return r.returncode, round(time.time() - t0, 1)


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:                                                  # noqa: BLE001
        return None


def irq_signature(d):
    """Flatten futex_irq_probe's summary into the flat keys blueprint_decide._io reads.

    add_irqio_to_pack.py did this transform when reading a sweep report; building packs
    per-run means doing it here. The probe reports {baseline, incident, x} per metric; the
    rules want `hardirq_x` and friends.
    """
    s = (d or {}).get("summary") or {}
    def x(k):
        return (s.get(k) or {}).get("x")
    def b(k):
        return (s.get(k) or {}).get("baseline")
    def i(k):
        return (s.get(k) or {}).get("incident")
    return {
        "hardirq_x": x("hardirq_s_per_s"),
        "hardirq_s_per_s_baseline": b("hardirq_s_per_s"),
        "hardirq_s_per_s_incident": i("hardirq_s_per_s"),
        "softirq_x": x("softirq_s_per_s"),
        "futex_p95_x": x("futex_p95_ms"),
        "futex_wait_x": x("futex_wait_s_per_s"),
        "futex_short_waits_x": x("futex_short_waits_per_s"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--family", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True, help="pack directory")
    ap.add_argument("--cache", default=os.environ.get("SLURM_TMPDIR", "/tmp"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    run_dir = os.path.join(V2, a.app, a.family, a.run)
    ctf = os.path.join(run_dir, "kernel", "kernel")
    pack_path = os.path.join(a.out, f"{a.run}.json")
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(os.path.join(a.out, "logs"), exist_ok=True)
    log = os.path.join(a.out, "logs", f"{a.run}.log")

    if os.path.exists(pack_path) and not a.force:
        print(f"SKIP {a.run} (pack exists)")
        return 0
    if not os.path.isdir(ctf):
        print(f"FAIL {a.run}: no CTF at {ctf}")
        return 1

    # A no-fault run has no injection window, so there is nothing to cut a baseline against.
    # Synthesised into the PACK dir, never into the dataset - the working copy stays as
    # collected.
    gt = os.path.join(run_dir, "ground_truth.json")
    if not os.path.exists(gt):
        gt = os.path.join(a.out, "logs", f"{a.run}.gt.json")
        if not os.path.exists(gt):
            rc, _ = run([sys.executable, SYNTH, "--ctf", ctf, "--out", gt], os.environ.copy(), log)
            if rc or not os.path.exists(gt):
                print(f"FAIL {a.run}: could not synthesise ground truth")
                return 1

    cache = os.path.join(a.cache, f"ctfcache_{a.run}")
    tmp = os.path.join(a.cache, f"packtmp_{a.run}")
    os.makedirs(tmp, exist_ok=True)
    timing, failed = {}, []

    try:
        rc, secs = run([sys.executable, EXTRACT, "--ctf", ctf, "--gt", gt, "--out", cache],
                       os.environ.copy(), log)
        timing["ctf_extract_s"] = secs
        env = os.environ.copy()
        if rc == 0:
            env["CTF_CACHE_DIR"] = cache        # a miss falls back to decoding, so a failed
                                                # extraction costs time, never correctness
        else:
            failed.append("ctf_extract (falling back to per-script decode)")

        for name, script, extra in STEPS:
            args = [sys.executable, script, "--ctf", ctf, "--gt", gt,
                    "--out", os.path.join(tmp, f"{name}.json")] + extra
            if name == "blocking":
                args += ["--comms", COMMS.get(a.app, "mysqld,java")]
            rc, secs = run(args, env, log)
            timing[f"{name}_s"] = secs
            if rc:
                failed.append(name)

        d = {n: load(os.path.join(tmp, f"{n}.json")) for n, _, _ in STEPS}

        def top(x, key, k, minc=0):
            rows = (x or {}).get(key, [])
            if minc:
                rows = [r for r in rows if r.get("n_incident", 0) >= minc]
            return rows[:k]

        pack = {
            "run_id": a.run, "app": a.app, "family_dir": a.family,
            "kernel_only": True,
            "source": "raw LTTng kernel trace (L0) read with babeltrace2",
            "timing_s": timing,
            "total_analysis_s": round(sum(timing.values()), 1),
            "measurements_failed": failed,
            "runqueue_delay": {
                "what": "per-wakeup delay between becoming runnable and getting a CPU; p95 "
                        "baseline vs incident, per process",
                "top_by_inflation": top(d["runqueue"], "comparison", 12, minc=500)},
            "blocking_syscall": {
                "what": "time spent inside each syscall between entry and exit; p95 baseline "
                        "vs incident, per (process, syscall)",
                "top_by_inflation": top(d["blocking"], "comparison", 14)},
            "oncpu": {
                "what": "on-CPU time per process from sched_switch, baseline vs incident: host "
                        "utilisation, and the cores each process gained or lost",
                "signature": (d["oncpu"] or {}).get("signature", {}),
                "top_gainers": (d["oncpu"] or {}).get("cores_delta", [])[:8]},
            "netloss": {
                "what": "per interface, the share of TCP segments repeating a sequence number "
                        "already seen on the same flow, and buffers queued but never sent",
                "signature": (d["netloss"] or {}).get("signature", {}),
                "worst": ((d["netloss"] or {}).get("comparison") or [])[:6]},
            "endpoints": {
                "what": "per flow, the gap from a request to the next response, baseline vs "
                        "incident",
                "signature": (d["endpoints"] or {}).get("signature", {}),
                "slowest": ((d["endpoints"] or {}).get("comparison") or [])[:6]},
            "blockio": {
                "what": "block layer: request arrivals per process, queue depth, device "
                        "service time",
                "signature": (d["blockio"] or {}).get("signature", {})},
            "irq": {
                "what": "hard and soft interrupt time per second, and futex wait shape",
                "signature": irq_signature(d["irq"])},
        }
        json.dump(pack, open(pack_path, "w"), indent=2)
        note = f"  ({len(failed)} failed: {','.join(failed)})" if failed else ""
        print(f"OK   {a.run}  {pack['total_analysis_s']}s{note}")
        return 0
    finally:
        # Several GB per run, 136 runs. Removed whether or not anything failed.
        shutil.rmtree(cache, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
