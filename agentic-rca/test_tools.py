#!/usr/bin/env python3
"""Exercise every agent tool across several runs and cross-check them against each other.

A per-tool smoke test only proves a tool RETURNS. It cannot tell you the answer is right.
These checks mostly compare two tools that must agree - ctf_timeline's series against
query_ctf's count over the same range, query_ctf against run_python over the same filter,
ctf_proclife's container count against the index. A disagreement is a bug in one of them, and
which one is usually obvious from the direction.

    python test_tools.py                 # the default five runs
    python test_tools.py RUN [RUN ...]

Reads ground truth NOWHERE. These are consistency checks, not accuracy checks.
"""
from __future__ import annotations
import os, sys, time, traceback

os.environ.setdefault("CTF_INDEX_ROOT", "/scratch/yuvraj17/stratatrace/dataset/index-v2")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codetool
import ctf_tool

DATA = "/scratch/yuvraj17/stratatrace/dataset/runs"

# five different fault families across both applications, so a bug that only shows up on one
# kind of workload has somewhere to show up
DEFAULT = [
    ("sockshop", "svc_cpu_cap", "svc_cpu_cap_aggressive_steady_r1"),
    ("sockshop", "anomaly_net", "anomaly_net_aggressive_burst_r1"),
    ("sockshop", "noisy_neighbor", "noisy_neighbor_aggressive_steady_r1"),
    ("trainticket", "slow_db", "tt_slow_db_aggressive_burst_r1"),
    ("trainticket", "deadlock", "tt_deadlock_aggressive_steady_r1"),
]

FAILS = []
NOTES = []


def check(run, name, ok, detail=""):
    print("   %-46s %s  %s" % (name, "PASS" if ok else "**FAIL**", detail))
    if not ok:
        FAILS.append((run, name, detail))


def note(run, name, detail):
    print("   %-46s note  %s" % (name, detail))
    NOTES.append((run, name, detail))


def secs(t):
    p = [float(x) for x in str(t).split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2]


def hms(s):
    return "%02d:%02d:%06.3f" % (int(s // 3600) % 24, int(s // 60) % 60, s % 60)


def one_run(app, family, rid):
    rd = os.path.join(DATA, app, family, rid)
    print()
    print("=" * 96)
    print("%s   (%s / %s)" % (rid, app, family))
    print("=" * 96)
    if not os.path.isdir(rd):
        check(rid, "run directory exists", False, rd)
        return
    sb = codetool.Sandbox(rid, index_root=os.environ["CTF_INDEX_ROOT"])

    # ---- 1. orientation -------------------------------------------------------------
    ts = ctf_tool.ctf_timespan(rd)
    ok = bool(ts.get("begin") and ts.get("end") and (ts.get("duration_s") or 0) > 0)
    check(rid, "ctf_timespan returns a span", ok,
          "%s -> %s (%.0fs)" % (ts.get("begin"), ts.get("end"), ts.get("duration_s") or 0))
    if not ok:
        sb.close()
        return
    t0, t1 = secs(ts["begin"]), secs(ts["end"])

    # run_python must see the same recording the other tools describe
    r = sb.run("print(round(T0,3), round(T1,3), len(df))")
    parts = (r.get("stdout") or "").split()
    if len(parts) == 3:
        p0, p1 = float(parts[0]), float(parts[1])
        check(rid, "run_python T0/T1 agree with ctf_timespan",
              abs(p0 - t0) < 0.5 and abs(p1 - t1) < 0.5,
              "tool %.1f-%.1f vs code %.1f-%.1f" % (t0, t1, p0, p1))
        check(rid, "run_python index is non-trivial", int(parts[2]) > 10000,
              "%s rows" % parts[2])
    else:
        check(rid, "run_python returns T0/T1/len", False, (r.get("error") or r)[:90])

    # ---- 2. counting: three tools over the SAME range must produce the SAME number ----
    EV = "sched_switch"
    tl = ctf_tool.ctf_timeline(rd, event=EV, buckets=30)
    # series items are {"t", "n", "bar"} - "n" is the count. Getting this wrong made the
    # first version of this test report a tool bug that was mine.
    series_sum = sum(int(b.get("n") or 0) for b in (tl.get("series") or []))
    q_all = ctf_tool.query_ctf(rd, event=EV, begin=ts["begin"], end=ts["end"])
    matched = int(q_all.get("matched") or 0)
    check(rid, "ctf_timeline series sums to its own matched",
          series_sum == int(tl.get("matched") or -1),
          "series %d vs matched %s" % (series_sum, tl.get("matched")))
    check(rid, "ctf_timeline matched == query_ctf over full span",
          int(tl.get("matched") or -1) == matched,
          "timeline %s vs query %d" % (tl.get("matched"), matched))

    rc = sb.run("m = df['event'] == %r\nprint(int(df.loc[m,'count'].sum()))" % EV)
    try:
        code_total = int((rc.get("stdout") or "0").strip())
    except ValueError:
        code_total = -1
    check(rid, "run_python total == query_ctf over full span",
          code_total == matched, "code %d vs query %d" % (code_total, matched))

    # a narrow range, where an off-by-one in bucket filtering would show up
    a0, a1 = t0 + 20, t0 + 30
    q_n = ctf_tool.query_ctf(rd, event=EV, begin=hms(a0), end=hms(a1))
    rc = sb.run("m = (df['event'] == %r) & (df['bucket_start_s'] >= %f) & "
                "(df['bucket_start_s'] < %f)\nprint(int(df.loc[m,'count'].sum()))"
                % (EV, a0, a1))
    try:
        code_n = int((rc.get("stdout") or "0").strip())
    except ValueError:
        code_n = -1
    check(rid, "run_python == query_ctf over a narrow range",
          code_n == int(q_n.get("matched") or 0),
          "code %d vs query %d" % (code_n, q_n.get("matched")))

    # A procname containing "#" used to silently wreck the whole frame: pandas treats "#" as
    # starting a comment anywhere in a line, and the JVM names its GC threads "GC Thread#7".
    # The tell is pid_ns arriving as float64 - NaN from truncated rows forces the column to
    # float - so check the dtype as well as the arithmetic, because the dtype names the cause.
    rc = sb.run("print(df['pid_ns'].dtype, df['pid_ns'].isna().sum(), df['count'].isna().sum())")
    parts = (rc.get("stdout") or "").split()
    check(rid, "index parses with no NaN (the 'GC Thread#7' bug)",
          len(parts) == 3 and "int" in parts[0] and parts[1] == "0" and parts[2] == "0",
          "pid_ns dtype=%s, NaN pid_ns=%s, NaN count=%s"
          % tuple(parts + ["?"] * (3 - len(parts))))
    rc = sb.run("h = df[df['procname'].str.contains('#', regex=False, na=False)]\n"
                "print(int(len(h)), int(h['count'].sum()))")
    parts = (rc.get("stdout") or "").split()
    if len(parts) == 2 and int(parts[0]) > 0:
        note(rid, "procnames containing '#'",
             "%s rows, %s events - these are the ones that used to vanish" % (parts[0], parts[1]))

    # ---- 3. containers --------------------------------------------------------------
    pl = ctf_tool.ctf_proclife(rd, min_events=1000)
    n_seen = pl.get("n_containers_seen")
    rc = sb.run("print(df['pid_ns'].nunique())")
    try:
        code_ns = int((rc.get("stdout") or "0").strip())
    except ValueError:
        code_ns = -1
    check(rid, "ctf_proclife names >1 container", (n_seen or 0) > 1, "n_containers_seen=%s" % n_seen)
    check(rid, "container count is plausible vs the index",
          code_ns > 1 and (n_seen or 0) <= code_ns,
          "proclife %s, index %d distinct pid_ns" % (n_seen, code_ns))
    lists = (pl.get("present_for_only_part_of_the_recording") or [],
             pl.get("present_throughout") or [])
    check(rid, "ctf_proclife returns BOTH lists", bool(lists[0]) or bool(lists[1]),
          "part=%d throughout=%d" % (len(lists[0]), len(lists[1])))

    # ---- 4. procdiff ----------------------------------------------------------------
    mid = (t0 + t1) / 2
    pd_ = ctf_tool.ctf_procdiff(rd, begin_a=hms(t0 + 5), end_a=hms(t0 + 35),
                                begin_b=hms(mid), end_b=hms(mid + 30), event=".")
    has = any(pd_.get(k) for k in ("only_in_a", "only_in_b", "biggest_changes"))
    check(rid, "ctf_procdiff compares two ranges", has,
          "a=%s b=%s changed=%s" % (len(pd_.get("only_in_a") or []),
                                    len(pd_.get("only_in_b") or []),
                                    len(pd_.get("biggest_changes") or [])))
    check(rid, "ctf_procdiff reports non-zero rates",
          (pd_.get("total_rate_a") or 0) > 0 and (pd_.get("total_rate_b") or 0) > 0,
          "a=%.0f/s b=%.0f/s" % (pd_.get("total_rate_a") or 0, pd_.get("total_rate_b") or 0))

    # ---- 5. raw lines, and the 400-char cut that hid the TCP header -------------------
    ln = ctf_tool.ctf_lines(rd, event=EV, begin=hms(a0), end=hms(a0 + 2), n=10)
    lines = ln.get("lines") or []
    check(rid, "ctf_lines returns lines", bool(lines), "returned=%s" % ln.get("returned"))
    check(rid, "ctf_lines reports the true population",
          isinstance(ln.get("total_in_range"), int) and ln["total_in_range"] > 0,
          "total_in_range=%s" % ln.get("total_in_range"))
    if lines:
        longest = max(len(x) for x in lines)
        check(rid, "raw lines are no longer cut at 400", longest > 400 or longest < 400,
              "longest kept line %d chars" % longest)

    net = ctf_tool.ctf_lines(rd, event="net_if_receive_skb", begin=hms(a0),
                             end=hms(a0 + 2), n=3)
    nl = net.get("lines") or []
    if nl:
        check(rid, "network lines carry the TCP header",
              any("seq =" in x for x in nl),
              "longest %d chars, seq present=%s"
              % (max(len(x) for x in nl), any("seq =" in x for x in nl)))
    else:
        note(rid, "network lines present", "no net_if_receive_skb in this window")

    # ---- 6. value_sum: the quantity, not the count -----------------------------------
    rc = sb.run(
        "m = df['event'] == 'sched_stat_runtime'\n"
        "print(int(df.loc[m,'count'].sum()), int(df.loc[m,'value_sum'].sum()))")
    parts = (rc.get("stdout") or "").split()
    if len(parts) == 2:
        cnt, val = int(parts[0]), int(parts[1])
        check(rid, "value_sum carries CPU nanoseconds", cnt > 0 and val > 0,
              "%d events, %.1f CPU-seconds" % (cnt, val / 1e9))
        check(rid, "CPU time is physically possible",
              0 < val / 1e9 < (t1 - t0) * 256,
              "%.1f CPU-s over %.0f wall-s" % (val / 1e9, t1 - t0))
    else:
        check(rid, "value_sum readable from run_python", False,
              (rc.get("error") or str(rc))[:90])

    # per-container CPU time: the aggregation svc_cpu_cap needs and no fixed tool expresses
    rc = sb.run(
        "m = df['event'] == 'sched_stat_runtime'\n"
        "g = df[m].groupby('pid_ns')['value_sum'].sum().sort_values(ascending=False)\n"
        "print(int((g > 0).sum()))\n"
        "for ns, v in g.head(3).items():\n"
        "    print(ns, round(v/1e9, 1))")
    out = (rc.get("stdout") or "").strip().splitlines()
    check(rid, "per-container CPU time is computable", len(out) >= 2 and int(out[0]) > 1,
          "%s containers with CPU time; top: %s"
          % (out[0] if out else "?", " | ".join(out[1:4])))

    sb.close()


def main():
    runs = DEFAULT
    if len(sys.argv) > 1:
        runs = []
        for rid in sys.argv[1:]:
            fam = rid[3:] if rid.startswith("tt_") else rid
            fam = fam.rsplit("_", 3)[0]
            app = "trainticket" if rid.startswith("tt_") else "sockshop"
            runs.append((app, fam, rid))
    t0 = time.time()
    for app, fam, rid in runs:
        try:
            one_run(app, fam, rid)
        except Exception:                                               # noqa: BLE001
            print(traceback.format_exc()[-900:])
            FAILS.append((rid, "unhandled exception", ""))
    print()
    print("=" * 96)
    print("%d runs in %.0fs   FAILURES: %d   notes: %d"
          % (len(runs), time.time() - t0, len(FAILS), len(NOTES)))
    for r, n, d in FAILS:
        print("  FAIL  %-34s %s  %s" % (r, n, d))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
