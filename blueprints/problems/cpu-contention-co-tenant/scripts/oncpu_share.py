#!/usr/bin/env python3
"""Who was actually ON the CPU, per process, baseline vs incident — from sched_switch alone.

Motivation (finding F1). Runqueue delay says *everyone is waiting*. It does not say why, and
it cannot: a co-tenant workload, a cgroup CPU cap and a saturated host all make threads wait.
On our `svc_cpu_cap` run runqueue delay reached 15.7x, more than double the 7.12x measured on
the actual co-tenant fault, so magnitude points the wrong way.

What separates co-tenant contention from the other two is that someone *took* the CPU: a
process that runs a lot during the incident and ran almost none in the baseline, and that is
not part of the application. This measures that directly, and needs no metrics — so it stays
within the kernel-only phase.

Method. sched_switch tells us, per CPU, which thread starts running and when. The previous
thread's on-CPU time on that CPU is the gap between consecutive switches:

    on_cpu[prev_comm] += t_now - t_last_switch_on_this_cpu

Reported per comm as a share of total CPU time in the window, baseline vs incident, so a
newcomer shows up as a share that rises from ~0.

    python3 oncpu_share.py --ctf <ctf_dir> --gt <ground_truth.json> --out oncpu.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, subprocess, sys

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
CPU = re.compile(r"\{ cpu_id = (\d+) \}")
SWITCH = re.compile(r'sched_switch:.*?prev_comm = "([^"]*)", prev_tid = (\d+).*?'
                    r'next_comm = "([^"]*)", next_tid = (\d+)')

# Kernel housekeeping threads. Idle time is not "taken" by anyone, and per-CPU kernel
# threads are not candidate culprits, so they are reported but never ranked as the thief.
IDLE_PREFIX = "swapper/"
KERNEL_HINTS = ("kworker", "ksoftirqd", "rcu_", "kswapd", "kcompactd", "migration",
                "watchdog", "irq/", "idle_inject", "cpuhp")


def is_kernel(comm):
    return comm.startswith(IDLE_PREFIX) or any(k in comm for k in KERNEL_HINTS)


def secs(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4)) / 1e9)


def hhmmss(iso):
    return iso.split("T")[1].rstrip("Z")


def unwrapper():
    """Trace timestamps are wall-clock time-of-day, so they wrap to zero at midnight. This
    returns a function that adds a day each time it sees the clock jump backwards, so a
    window crossing midnight still has monotonic time and a positive span."""
    state = {"day": 0.0, "prev": None}

    def fix(t):
        if state["prev"] is not None and t < state["prev"] - 43200:
            state["day"] += 86400.0
        state["prev"] = t
        return t + state["day"]
    return fix


def scan(ctf, begin, end):
    """Decode one window; return {comm: on_cpu_seconds} and the window's wall span."""
    p1 = subprocess.Popen([BT2, ctf, "--begin", begin, "--end", end],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env={**os.environ, "TZ": "UTC"})
    p2 = subprocess.Popen(["grep", "sched_switch"], stdin=p1.stdout,
                          stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()

    unwrap = unwrapper()   # window may cross midnight

    last = {}                                    # cpu -> (t, comm_currently_running)
    on_cpu = collections.defaultdict(float)
    t_first = t_last = None
    for line in p2.stdout:
        mt, mc, ms = TS.match(line), CPU.search(line), SWITCH.search(line)
        if not (mt and mc and ms):
            continue
        t, cpu = unwrap(secs(mt)), int(mc.group(1))
        prev_comm, next_comm = ms.group(1), ms.group(3)
        if t_first is None:
            t_first = t
        t_last = t

        prior = last.get(cpu)
        if prior is not None:
            t0, running = prior
            d = t - t0
            if 0 <= d < 10.0:                    # guard against window-edge artifacts
                on_cpu[running] += d
        last[cpu] = (t, next_comm)
        # prev_comm is a consistency check only; the running comm is tracked per CPU
        del prev_comm

    p2.stdout.close()
    for p in (p2, p1):
        try:
            p.terminate()
        except Exception:                                              # noqa: BLE001
            pass
    span = (t_last - t_first) if (t_first is not None and t_last is not None) else 0.0
    # How many CPUs the trace actually saw. Needed for the saturation test: a co-tenant
    # leaves headroom, a saturated host does not, and "busy cores" means nothing without
    # knowing how many there are.
    n_cpus = (max(last) + 1) if last else 0
    return dict(on_cpu), span, n_cpus


def summarise(on_cpu, span, n_cpus):
    """Shares of BUSY cpu time (idle excluded), plus absolute cores used."""
    busy = {c: v for c, v in on_cpu.items() if not c.startswith(IDLE_PREFIX)}
    total_busy = sum(busy.values()) or 1e-9
    rows = []
    for comm, v in busy.items():
        rows.append({"comm": comm,
                     "cpu_seconds": round(v, 3),
                     "share_of_busy": round(v / total_busy, 5),
                     "cores": round(v / span, 4) if span else None,
                     "kernel_thread": is_kernel(comm)})
    rows.sort(key=lambda r: -r["cpu_seconds"])
    busy_cores = (total_busy / span) if span else 0.0
    return {"window_span_s": round(span, 3),
            "n_cpus": n_cpus,
            "busy_cpu_seconds": round(total_busy, 3),
            "busy_cores": round(busy_cores, 3),
            # THE saturation test. Co-tenant contention leaves headroom; host saturation
            # does not. Both raise runqueue delay, so this is what separates them.
            "host_utilisation": round(busy_cores / n_cpus, 4) if n_cpus else None,
            "per_comm": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="oncpu.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    ap.add_argument("--newcomer-cores", type=float, default=0.25,
                    help="a comm must gain at least this many cores to be called a newcomer")
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])

    def shift(hms, d):
        h, m, s = (int(x) for x in hms.split(":"))
        # wrap into a valid time of day: a window may legitimately cross midnight,
        # and "24:00:21" is not a time the trace reader accepts
        v = (h * 3600 + m * 60 + s + d) % 86400
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    windows = {"baseline": (shift(t0, -a.baseline_s), t0),
               "incident": (t0, shift(t0, a.incident_s))}

    result = {"ctf": a.ctf, "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        on_cpu, span, n_cpus = scan(a.ctf, b, e)
        result["windows"][name] = {"range": [b, e], **summarise(on_cpu, span, n_cpus)}
        w = result["windows"][name]
        print(f"  {len(on_cpu)} comms, busy {w['busy_cores']} of {n_cpus} cores "
              f"({100 * (w['host_utilisation'] or 0):.0f}% util) over {span:.1f}s")

    base = {r["comm"]: r for r in result["windows"]["baseline"]["per_comm"]}
    inc = {r["comm"]: r for r in result["windows"]["incident"]["per_comm"]}

    # The thief test: cores gained between the windows. A co-tenant appears from nothing;
    # a throttled service LOSES cpu; a saturated host raises many comms at once.
    deltas = []
    for comm in sorted(set(base) | set(inc)):
        b, i = base.get(comm), inc.get(comm)
        bc = (b or {}).get("cores") or 0.0
        ic = (i or {}).get("cores") or 0.0
        deltas.append({
            "comm": comm,
            "cores_baseline": round(bc, 4), "cores_incident": round(ic, 4),
            "cores_gained": round(ic - bc, 4),
            "share_baseline": (b or {}).get("share_of_busy", 0.0),
            "share_incident": (i or {}).get("share_of_busy", 0.0),
            "kernel_thread": is_kernel(comm),
            # "newcomer" = took real CPU it was not taking before. The baseline test is
            # deliberately loose (10x or from near-zero) because a co-tenant starts at zero.
            "newcomer": bool(ic - bc >= a.newcomer_cores and (bc < 0.05 or ic / max(bc, 1e-9) >= 10)),
        })
    deltas.sort(key=lambda r: -r["cores_gained"])
    result["cores_delta"] = deltas
    result["newcomers"] = [d for d in deltas if d["newcomer"] and not d["kernel_thread"]]
    result["biggest_loser"] = min(deltas, key=lambda r: r["cores_gained"]) if deltas else None

    # The three facts that should separate the CPU cluster. Reported as measurements only —
    # which combination means which fault is decided after looking at all the families,
    # not asserted here.
    wb, wi = result["windows"]["baseline"], result["windows"]["incident"]
    top_new = result["newcomers"][0] if result["newcomers"] else None
    loser = result["biggest_loser"]
    result["signature"] = {
        "host_util_baseline": wb["host_utilisation"],
        "host_util_incident": wi["host_utilisation"],
        "busy_cores_baseline": wb["busy_cores"],
        "busy_cores_incident": wi["busy_cores"],
        "n_cpus": wi["n_cpus"],
        "thief_comm": top_new["comm"] if top_new else None,
        "thief_cores_gained": top_new["cores_gained"] if top_new else 0.0,
        "biggest_loser_comm": loser["comm"] if loser else None,
        "biggest_loser_cores": loser["cores_gained"] if loser else 0.0,
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'comm':24s} {'base':>8s} {'inc':>8s} {'gained':>8s}  new?")
    for d in deltas[:12]:
        print(f"{d['comm']:24s} {d['cores_baseline']:8.3f} {d['cores_incident']:8.3f} "
              f"{d['cores_gained']:8.3f}  {'YES' if d['newcomer'] else ''}")
    if result["newcomers"]:
        n = result["newcomers"][0]
        print(f"\nnewcomer: {n['comm']} gained {n['cores_gained']} cores "
              f"({n['cores_baseline']} -> {n['cores_incident']})")
    else:
        print("\nno newcomer process: nothing took CPU that was not already taking it")


if __name__ == "__main__":
    sys.exit(main())
