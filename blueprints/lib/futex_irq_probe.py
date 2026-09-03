#!/usr/bin/env python3
"""Lock waits and interrupt time — two signals already sitting in every run we collected.

WHY THIS EXISTS
---------------
Naser asked for a kernel lock-contention blueprint. We may not need to collect anything: our
profile enables `--syscall --all`, and **futex is a syscall**, so every lock wait in all 109
runs is already on disk. The profile also enables `irq_*`/`softirq_*`. Neither has ever been
read by any of our code - `futex` appears once, as a name in a counting list.

WHAT IT MEASURES
----------------
futex   pair syscall_entry_futex -> syscall_exit_futex per thread and time the gap. A thread
        parked on a contended lock shows up as a long futex wait. FUTEX_WAKE returns at once,
        so short calls are the wake side and long ones are the wait side.

softirq pair irq_softirq_entry -> irq_softirq_exit per (cpu, vector) and total the time.
        Vector 3 is NET_RX: if softirq is eating the machine, packets are being processed at
        the expense of everything else.

hardirq same for irq_handler_entry -> irq_handler_exit, per device name.

WHAT WE EXPECT, AND WHY THAT IS THE POINT
-----------------------------------------
We never injected a lock-contention fault. So the honest question is not "does futex find our
faults" - it is **"does futex stay quiet for all 13 faults we DO have?"** If it does, then a
future rise in futex wait means lock contention and not something else. That is the negative
control a blueprint needs before it can claim anything, and it is exactly the check we skipped
on packet loss (finding F17), which then fired on a memory cap harder than on any network
fault.

    python3 futex_irq_probe.py --ctf <ctf> --gt <ground_truth> --out probe.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctf_stream                                                      # noqa: E402

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
EVENT = re.compile(r" ([a-z_0-9]+): \{")
CPU = re.compile(r"\{ cpu_id = (\d+) \}")
TID = re.compile(r"\btid = (\d+)")
PROC = re.compile(r'procname = "([^"]*)"')
VEC = re.compile(r"\bvec = (\d+)")
IRQNAME = re.compile(r'(?<![A-Za-z])name = "([^"]*)"')

# Linux softirq vectors, so the output names them instead of printing bare numbers
SOFTIRQ = {0: "HI", 1: "TIMER", 2: "NET_TX", 3: "NET_RX", 4: "BLOCK",
           5: "IRQ_POLL", 6: "TASKLET", 7: "SCHED", 8: "HRTIMER", 9: "RCU"}

LONG_WAIT_S = 0.001          # a futex call over 1 ms is a real block, not a fast wake

# MEASURED, first run (noisy_neighbor r1): total futex wait was 408 SECONDS per second of wall
# clock, and java alone waited 6684 s over 22036 calls - about 300 ms a call. That is not
# contention, it is thread pools PARKED waiting for work. Raw futex wait time is dominated by
# idle parking and cannot detect a contended lock on its own.
#
# A contended lock looks different in shape: many waits, each short, because the holder
# releases quickly and the waiter is woken and re-blocks. Idle parking is few waits, each long.
# So bucket the durations instead of trusting a single total.
BUCKETS = [(0.0, 1e-4, "<100us"), (1e-4, 1e-3, "100us-1ms"), (1e-3, 1e-2, "1-10ms"),
           (1e-2, 1e-1, "10-100ms"), (1e-1, 1.0, "100ms-1s"), (1.0, 1e9, ">1s")]


def bucketise(durs):
    out = {name: 0 for _, _, name in BUCKETS}
    for d in durs:
        for lo, hi, name in BUCKETS:
            if lo <= d < hi:
                out[name] += 1
                break
    return out


def secs(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4)) / 1e9)


def hhmmss(iso):
    return iso.split("T")[1].rstrip("Z")


def unwrapper():
    """Timestamps are time-of-day and wrap at midnight (finding F8)."""
    state = {"day": 0.0, "prev": None}

    def fix(t):
        if state["prev"] is not None and t < state["prev"] - 43200:
            state["day"] += 86400.0
        state["prev"] = t
        return t + state["day"]
    return fix


def pct(v, p):
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(p * len(s)))] * 1e3, 3)      # ms


def scan(ctf, begin, end):
    unwrap = unwrapper()
    fx_open = {}                                   # tid -> entry time
    fx_dur = []                                    # every completed futex call, seconds
    fx_by_comm = collections.defaultdict(list)     # comm -> long waits
    fx_calls = 0

    si_open = {}                                   # (cpu, vec) -> entry time
    si_time = collections.Counter()                # vec -> seconds inside softirq
    si_count = collections.Counter()

    hi_open = {}                                   # (cpu, name) -> entry time
    hi_time = collections.Counter()
    hi_count = collections.Counter()

    t_first = t_last = None
    src, handles = ctf_stream.open_lines(
        ctf, begin, end, ctf_stream.FAMILIES["lockirq"], family="lockirq")
    for line in src:
        mt, me = TS.match(line), EVENT.search(line)
        if not (mt and me):
            continue
        t, ev = unwrap(secs(mt)), me.group(1)
        if t_first is None:
            t_first = t
        t_last = t

        if ev == "syscall_entry_futex":
            m = TID.search(line)
            if m:
                fx_open[m.group(1)] = (t, (PROC.search(line) or [None, "?"])[1]
                                       if PROC.search(line) else "?")
        elif ev == "syscall_exit_futex":
            m = TID.search(line)
            if m and m.group(1) in fx_open:
                t0, comm = fx_open.pop(m.group(1))
                d = t - t0
                if 0 <= d < 60:                    # ignore window-edge artefacts
                    fx_calls += 1
                    fx_dur.append(d)
                    if d >= LONG_WAIT_S:
                        fx_by_comm[comm].append(d)
        elif ev == "irq_softirq_entry":
            mc, mv = CPU.search(line), VEC.search(line)
            if mc and mv:
                si_open[(mc.group(1), mv.group(1))] = t
        elif ev == "irq_softirq_exit":
            mc, mv = CPU.search(line), VEC.search(line)
            if mc and mv:
                k = (mc.group(1), mv.group(1))
                if k in si_open:
                    d = t - si_open.pop(k)
                    if 0 <= d < 1:
                        si_time[int(mv.group(1))] += d
                        si_count[int(mv.group(1))] += 1
        elif ev == "irq_handler_entry":
            mc, mn = CPU.search(line), IRQNAME.search(line)
            if mc and mn:
                hi_open[(mc.group(1), mn.group(1))] = t
        elif ev == "irq_handler_exit":
            mc = CPU.search(line)
            if mc:
                for k in [k for k in hi_open if k[0] == mc.group(1)]:
                    d = t - hi_open.pop(k)
                    if 0 <= d < 1:
                        hi_time[k[1]] += d
                        hi_count[k[1]] += 1
                    break
    ctf_stream.close_lines(handles)

    span = (t_last - t_first) if (t_first is not None and t_last is not None) else 0.0
    long_waits = [d for d in fx_dur if d >= LONG_WAIT_S]
    top = sorted(((c, sum(v), len(v)) for c, v in fx_by_comm.items()),
                 key=lambda r: (-r[1], r[0]))[:8]
    return {
        "window_span_s": round(span, 3),
        "futex": {
            "calls": fx_calls,
            "calls_per_s": round(fx_calls / span, 1) if span else None,
            "total_wait_s": round(sum(fx_dur), 3),
            "p50_ms": pct(fx_dur, 0.50), "p95_ms": pct(fx_dur, 0.95),
            "p99_ms": pct(fx_dur, 0.99),
            "long_waits": len(long_waits),
            "long_wait_s": round(sum(long_waits), 3),
            # the shape, not just the total - see BUCKETS above
            "buckets": bucketise(fx_dur),
            "short_waits": sum(1 for d in fx_dur if d < LONG_WAIT_S),
            "top_waiters": [{"comm": c, "wait_s": round(s, 3), "n": n} for c, s, n in top],
        },
        "softirq": {
            "total_s": round(sum(si_time.values()), 4),
            "by_vector": {SOFTIRQ.get(v, str(v)): round(s, 4)
                          for v, s in sorted(si_time.items(), key=lambda kv: -kv[1])},
            "count_by_vector": {SOFTIRQ.get(v, str(v)): n
                                for v, n in sorted(si_count.items(), key=lambda kv: -kv[1])},
        },
        "hardirq": {
            "total_s": round(sum(hi_time.values()), 4),
            "by_device": {k: round(v, 4)
                          for k, v in sorted(hi_time.items(), key=lambda kv: -kv[1])[:8]},
        },
    }


def ratio(a, b):
    if a in (None, 0) or b is None:
        return None
    return round(b / a, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="futex_irq.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])
    wins = ctf_stream.windows(t0, a.baseline_s, a.incident_s)

    got = {}
    for name, (b, e) in wins.items():
        print(f"scanning {name}: {b} -> {e} ...", flush=True)
        got[name] = scan(a.ctf, b, e)

    base, inc = got["baseline"], got["incident"]
    bs = max(base["window_span_s"], 1e-9)
    is_ = max(inc["window_span_s"], 1e-9)

    # rates, so the two windows compare fairly even at different lengths
    def rate(w, span, *keys):
        d = w
        for k in keys:
            d = d.get(k, {}) if isinstance(d, dict) else 0
        return (d / span) if isinstance(d, (int, float)) else None

    summary = {
        "futex_long_waits_per_s": {
            "baseline": round(base["futex"]["long_waits"] / bs, 2),
            "incident": round(inc["futex"]["long_waits"] / is_, 2)},
        "futex_wait_s_per_s": {
            "baseline": round(base["futex"]["long_wait_s"] / bs, 3),
            "incident": round(inc["futex"]["long_wait_s"] / is_, 3)},
        "futex_p95_ms": {"baseline": base["futex"]["p95_ms"],
                         "incident": inc["futex"]["p95_ms"]},
        # short waits are the contention-shaped ones; parking sits in the long buckets
        "futex_short_waits_per_s": {
            "baseline": round(base["futex"]["short_waits"] / bs, 2),
            "incident": round(inc["futex"]["short_waits"] / is_, 2)},
        "softirq_s_per_s": {"baseline": round(base["softirq"]["total_s"] / bs, 4),
                            "incident": round(inc["softirq"]["total_s"] / is_, 4)},
        "hardirq_s_per_s": {"baseline": round(base["hardirq"]["total_s"] / bs, 4),
                            "incident": round(inc["hardirq"]["total_s"] / is_, 4)},
    }
    for k, v in list(summary.items()):
        v["x"] = ratio(v["baseline"], v["incident"])
    net_rx = {w: got[w]["softirq"]["by_vector"].get("NET_RX", 0.0) for w in got}
    summary["softirq_NET_RX_s_per_s"] = {
        "baseline": round(net_rx["baseline"] / bs, 4),
        "incident": round(net_rx["incident"] / is_, 4),
        "x": ratio(net_rx["baseline"] / bs, net_rx["incident"] / is_)}

    result = {"ctf": a.ctf, "gt": a.gt,
              "family": gt.get("name"), "target": gt.get("target_service"),
              "windows": {k: list(v) for k, v in wins.items()},
              "summary": summary, "baseline": base, "incident": inc}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)

    print(f"\nwrote {a.out}\n")
    print(f"{'signal':28s} {'baseline':>10s} {'incident':>10s} {'x':>7s}")
    for k, v in summary.items():
        print(f"{k:28s} {str(v['baseline']):>10s} {str(v['incident']):>10s} "
              f"{str(v['x']):>7s}")
    if inc["futex"]["top_waiters"]:
        print("\ntop futex waiters in the incident window:")
        for r in inc["futex"]["top_waiters"][:5]:
            print(f"   {r['comm'][:24]:24s} {r['wait_s']:8.3f} s over {r['n']} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
