#!/usr/bin/env python3
"""query_ctf / ctf_timeline — let the agent interrogate the RAW LTTng trace like an engineer.

THE RULE THIS FILE EXISTS TO ENFORCE
------------------------------------
**Nothing here may read ground_truth.json.** A real engineer handed a trace does not know when
the incident started, what kind it was, or which component caused it. They scan, notice
something change, narrow in, and argue from evidence. The agent must do the same, or we are
not measuring root-cause analysis - we are measuring whether it can describe a window somebody
already pointed at.

An earlier version of this file took `window="incident"` and resolved it from
`ground_truth.json.injection_start_utc`. That handed over the answer to "when". Removed.

WHAT THE AGENT GETS INSTEAD
---------------------------
  ctf_timespan   the trace's own start and end, from the trace. The only free orientation.
  ctf_timeline   counts of an event bucketed across the WHOLE trace - this is the change-point
                 finder. A step in the series is where something happened, and the agent has to
                 spot it rather than be told.
  query_ctf      counts, top processes and real event lines for an arbitrary [begin, end)
                 the AGENT chooses.

So the workflow is the human one: orient, scan for a change, form a hypothesis, compare a
window you suspect against one you believe is quiet, and name what, when and where.

THE CONSTRAINT THAT SHAPES THE BOUNDS
-------------------------------------
One incident is ~20 MILLION kernel events and a full decode costs ~745 s. Nothing may stream
the whole trace into a context window, so every call is capped: a time range is required for
query_ctf, an event pattern is always required, raw lines are capped at 40, and a scan cap
protects wall clock. A truncated read says so explicitly - a silent partial answer is worse
than an error, because the agent would treat a lower bound as a count.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
from collections import Counter

# babeltrace 2.1.2. 2.0.4 CANNOT read these traces and the wrapper silently falls back to it if
# its paths go stale - check `bt21.sh --version` if a query comes back empty (CLUSTER-LAYOUT.md).
BT2 = os.environ.get("BT2", "/scratch/yuvraj17/stratatrace/tools/bt21.sh")

# --clock-gmt on EVERY call. babeltrace2 renders timestamps in the reader's LOCAL time by
# default, so on this cluster the trace read 09:10 where the run actually happened at 13:11 UTC
# - a 4-hour EDT offset. Every other artifact in a bundle is UTC (ground truth, meta ticks,
# container logs), so without this the agent's window can never line up with anything, and a
# correct finding scores as a miss.
GMT = ["--clock-gmt"]

MAX_SAMPLE = 40
MAX_SCAN = 400000
# ctf_lines decodes from the start of the trace, so a wide range is a full pass for a
# handful of lines. Counts come from the index; lines are for confirming what an event
# looks like once the counts have said where to look.
MAX_LINES_RANGE_S = 5.0
# How many processes query_ctf names. 15 was too few and it was nearly luck that it was
# enough: measured on noisy_neighbor r1, the injected `stress-ng-cpu` is 1.68M events
# against dockerd's 67M, so it ranked 15th of 15 inside its own incident window - one
# place from invisible. The agent finds the culprit by noticing a process present in
# one range and absent from another, so the list has to be long enough for that
# comparison to be possible rather than fortunate.
TOP_PROCS = 30
_TIME_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d+)\]")
_EVENT_RE = re.compile(r"\]\s+(?:\(\+[^)]*\)\s+)?\S+\s+([a-zA-Z0-9_]+):")
_PROC_RE = re.compile(r'procname\s*=\s*"([^"]*)"')


def _secs(hhmmss: str) -> float:
    h, m, s = hhmmss.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _secs_safe(hhmmss: str):
    """_secs, but None instead of an exception. begin/end come from the model, so they can be
    anything; a malformed range must not take the whole tool call down."""
    try:
        return _secs(hhmmss)
    except (ValueError, AttributeError):
        return None


def _clock(line: str):
    m = _TIME_RE.match(line)
    if not m:
        return None
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + float("0." + m.group(4)))


def _fmt(sec: float) -> str:
    sec = max(0.0, sec)
    return "%02d:%02d:%06.3f" % (int(sec) // 3600 % 24, int(sec) // 60 % 60, sec % 60)


_TICK_RE = re.compile(r"_tick_(\d{8})T(\d{6})Z\.txt$")


# ---------------------------------------------------------------------------
# The count index. See blueprints/lib/build_ctf_index.py for how it is built and why.
#
# babeltrace2 does not seek: --begin/--end decode from the start of the trace and discard the
# rest, so a query's cost tracks how DEEP the range sits, not how much comes back. Measured
# here: a 1 s range 3 s in costs 9.6 s; the same 1 s range 213 s in costs 133 s. The scan cap
# that keeps one call bounded was therefore giving the agent the first 0.3 s of a 20 s window
# - 1.6% - and it went on to compare two 0.3 s slices as though they were the windows it asked
# for. Counts now come from a table built by ONE full pass, so a range means the whole range.
#
# The index holds counts and nothing else: bucket_start_s, event, procname, count. It reads no
# ground truth, and has no notion of a baseline, an incident window, a fault or a culprit. It
# is built before any question is asked of it and identically for every run.
#
# Raw event LINES still come from the trace itself, through ctf_lines.
INDEX_ROOT = os.environ.get("CTF_INDEX_ROOT", "/scratch/yuvraj17/stratatrace/data/ctf-index")


def _index_for(run_dir: str):
    p = os.path.join(INDEX_ROOT, os.path.basename(run_dir.rstrip("/")) + ".tsv.gz")
    return p if os.path.exists(p) else None


def _scan_index(path: str, ev_re=None, procname: str | None = None,
                t0: float | None = None, t1: float | None = None):
    """Stream matching index rows as (bucket_start_s, event, procname, count)."""
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            try:
                b, ev, proc, n = line.rstrip().split('\t')
                bt = float(b)
            except ValueError:
                continue
            if t0 is not None and bt < t0:
                continue
            if t1 is not None and bt >= t1:
                continue
            if ev_re is not None and not ev_re.search(ev):
                continue
            if procname is not None and proc != procname:
                continue
            yield bt, ev, proc, int(n)


def ctf_timespan(run_dir: str, ctf_subdir: str = "kernel/kernel") -> dict:
    """How long the recording is. Read from the bundle's own collection metadata.

    NOT by decoding the trace. The first version did, hit a 4-million-event cap, and returned
    the partial read AS IF IT WERE THE WHOLE SPAN - it reported 3.6 s of a 219 s recording, and
    the agent then reasoned, honestly, from a tool that had lied to it. A capped read presented
    as complete is worse than an error.

    `meta/` carries periodic cgroup snapshots stamped `_tick_YYYYMMDDTHHMMSSZ`, written
    throughout collection. Their first and last stamps bound the recording. This is collection
    metadata - WHEN THE RECORDER RAN - which any engineer handed a trace would know. It is not
    `ground_truth.json`, which records when the FAULT was injected, and which nothing in this
    file may read.
    """
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}

    # Prefer the index: it was built from every event in the trace, so it knows the real ends.
    # The tick snapshots start a little after the recorder does and stop a little before it,
    # and on noisy_neighbor r1 that cost 12 s at each end - 13:11:07-13:14:46 against a true
    # 13:10:55-13:14:58. That matters because the agent is told every range must sit inside
    # this span, so an under-reported span silently puts the first and last 12 s off limits.
    idx = _index_for(run_dir)
    if idx is not None:
        lo_t = hi_t = None
        for bt, _ev, _proc, _n in _scan_index(idx):
            if lo_t is None:
                lo_t = bt
            hi_t = bt
        if lo_t is not None:
            return {
                "begin": _fmt(lo_t), "end": _fmt(hi_t),
                "duration_s": round(hi_t - lo_t, 1), "clock": "UTC",
                "source": "the trace itself, via the count index",
                "note": ("This is the whole recording, in UTC. Nothing here says where an "
                         "incident is or whether there is one - use ctf_timeline to look for a "
                         "change across this span, then query_ctf on any range you suspect."),
            }

    meta = os.path.join(run_dir, "meta")
    stamps = []
    if os.path.isdir(meta):
        for fn in os.listdir(meta):
            m = _TICK_RE.search(fn)
            if m:
                hh, mm, ss = m.group(2)[:2], m.group(2)[2:4], m.group(2)[4:6]
                stamps.append("%s:%s:%s" % (hh, mm, ss))
    if not stamps:
        return {"error": "no meta/_tick_ snapshots - cannot bound the recording without "
                         "decoding, and a capped decode would misreport the span"}
    stamps.sort()
    lo, hi = stamps[0], stamps[-1]
    dur = _secs(hi) - _secs(lo)
    return {
        "begin": lo, "end": hi, "duration_s": round(dur, 1),
        "clock": "UTC",
        "source": "meta/ cgroup tick snapshots written during collection "
                  "(approximate: they begin just after, and end just before, the "
                  "recorder itself)",
        "note": ("This is the whole recording, in UTC. Nothing here says where an incident is "
                 "or whether there is one - use ctf_timeline to look for a change across this "
                 "span, then query_ctf to inspect any range you suspect."),
    }


def ctf_timeline(run_dir: str, event: str, buckets: int = 30,
                 procname: str | None = None, ctf_subdir: str = "kernel/kernel") -> dict:
    """Count one event across the WHOLE trace, bucketed in time. The change-point finder.

    This is what replaces being told when the incident was. A rate that steps up or collapses
    partway through the series is the thing to investigate - but the agent decides that, and
    has to defend it from the numbers.

    Served from the count index, so the series really does span the whole recording. The first
    version decoded the trace under a scan cap and drew a full-width chart from whatever
    prefix it managed to read, which meant "no clearly isolated step" could equally mean
    "I never looked at most of it".
    """
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}
    buckets = max(5, min(int(buckets), 120))

    idx = _index_for(run_dir)
    if idx is None:
        return _timeline_from_trace(run_dir, event, buckets, procname, ctf_subdir)

    rows = list(_scan_index(idx, ev_re=ev_re, procname=procname))
    if not rows:
        return {"event_pattern": event, "matched": 0, "source": "count index",
                "note": ("no events matched - check the pattern, or this tracepoint was not "
                         "enabled in the collection profile")}

    lo = min(r[0] for r in rows)
    hi = max(r[0] for r in rows)
    width = max(1e-6, (hi - lo) / buckets)
    counts = [0] * buckets
    matched = 0
    for bt, _ev, _proc, n in rows:
        counts[min(buckets - 1, int((bt - lo) / width))] += n
        matched += n
    peak = max(counts)
    series = [{"t": _fmt(lo + i * width), "n": c,
               "bar": "#" * int(round(20 * c / peak)) if peak else ""}
              for i, c in enumerate(counts)]
    names = Counter()
    for _bt, ev, _proc, n in rows:
        names[ev] += n
    return {
        "event_pattern": event, "procname": procname, "clock": "UTC",
        "span_covered": [_fmt(lo), _fmt(hi)], "bucket_width_s": round(width, 3),
        "matched": matched, "by_event": dict(names.most_common(10)),
        "source": "count index (one full decode; this series covers the whole recording)",
        "series": series,
        "how_to_read": ("Each row is one time bucket and its event count. A sustained step up "
                        "or down partway through is a candidate change point. Confirm it "
                        "against a second, unrelated event before believing it - a step in "
                        "every event type usually means the workload changed, not the system."),
    }


def query_ctf(run_dir: str, event: str, begin: str | None = None, end: str | None = None,
              procname: str | None = None, buckets: int = 0,
              ctf_subdir: str = "kernel/kernel", sample: int = 0,
              contains: str | None = None) -> dict:
    """Counts, rate and responsible processes for one event over a range THE AGENT chooses.

    begin/end are clock strings like '13:12:30' (HH:MM:SS[.frac]), UTC. Omit both for the whole
    recording. There are no named windows: naming one would require knowing when the incident
    was, which is the thing being asked.

    Exact over the full range, from the count index - not a capped prefix of it.
    """
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}

    idx = _index_for(run_dir)
    if idx is None:
        return _query_from_trace(run_dir, event, begin, end, sample or 10, procname,
                                 contains, ctf_subdir)

    t0 = _secs_safe(begin) if begin else None
    t1 = _secs_safe(end) if end else None
    if begin and t0 is None:
        return {"error": "cannot parse begin %r - use HH:MM:SS" % begin}
    if end and t1 is None:
        return {"error": "cannot parse end %r - use HH:MM:SS" % end}
    if t0 is not None and t1 is not None and t1 <= t0:
        return {"error": "end must be after begin"}

    by_event, by_proc = Counter(), Counter()
    per_bucket = Counter()
    lo = hi = None
    for bt, ev, proc, n in _scan_index(idx, ev_re=ev_re, procname=procname, t0=t0, t1=t1):
        by_event[ev] += n
        by_proc[proc] += n
        per_bucket[bt] += n
        lo = bt if lo is None else min(lo, bt)
        hi = bt if hi is None else max(hi, bt)

    total = sum(by_event.values())
    span = (t1 - t0) if (t0 is not None and t1 is not None) else (
        (hi - lo) if (lo is not None and hi is not None) else None)
    out = {
        "event_pattern": event,
        "range_requested": [begin, end],
        "filters": {"procname": procname},
        "clock": "UTC",
        "matched": total,
        "rate_per_s": round(total / span, 2) if span and span > 0 else None,
        "by_event": dict(by_event.most_common(15)),
        "top_procnames": dict(by_proc.most_common(TOP_PROCS)),
        "source": "count index (exact over the whole range you asked for)",
        "how_to_compare": ("A count on its own means nothing. Compare rate_per_s against "
                           "another range of this same trace that you have reason to believe "
                           "is quiet, and say which range you used and why."),
    }
    if total == 0:
        # An honest zero, unlike the old capped read where zero meant "not in the 0.3 s I got to".
        out["note"] = ("zero over this whole range. The range really was read end to end, so "
                       "this means absent here - not merely unread. Check the pattern is right "
                       "before concluding anything from it.")
    if buckets:
        b = max(5, min(int(buckets), 120))
        keys = sorted(per_bucket)
        if keys:
            klo, khi = keys[0], keys[-1]
            w = max(1e-6, (khi - klo) / b)
            cc = [0] * b
            for k in keys:
                cc[min(b - 1, int((k - klo) / w))] += per_bucket[k]
            peak = max(cc)
            out["series"] = [{"t": _fmt(klo + i * w), "n": c,
                              "bar": "#" * int(round(20 * c / peak)) if peak else ""}
                             for i, c in enumerate(cc)]
            out["bucket_width_s"] = round(w, 3)
    if sample:
        out["sample_note"] = ("This tool returns counts only. For real event lines with their "
                              "fields, call ctf_lines over a narrow range.")
    return out


def ctf_lines(run_dir: str, event: str, begin: str, end: str, n: int = 10,
              procname: str | None = None, contains: str | None = None,
              ctf_subdir: str = "kernel/kernel") -> dict:
    """Real event lines, with their fields, straight from the trace.

    Separate from query_ctf on purpose. Counting is cheap now because it reads the index;
    reading actual lines is not, because it decodes the trace from the beginning every time.
    Keeping them apart means the expensive path is a deliberate choice rather than a hidden
    cost on every count.

    Narrow ranges only, and few lines: this is for confirming WHAT an event looks like once
    the counts have told you where to look.
    """
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}
    t0, t1 = _secs_safe(begin), _secs_safe(end)
    if t0 is None or t1 is None or t1 <= t0:
        return {"error": "begin and end are required, as HH:MM:SS, with end after begin"}
    if t1 - t0 > MAX_LINES_RANGE_S:
        return {"error": "range is %.1f s; ask for at most %d s of lines. Use query_ctf for "
                         "counts over wider ranges." % (t1 - t0, MAX_LINES_RANGE_S)}
    n = max(1, min(int(n), MAX_SAMPLE))

    cmd = [BT2] + GMT + [ctf, "--begin", begin, "--end", end]
    lines, scanned = [], 0
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, bufsize=1 << 20)
    except OSError as e:
        return {"error": "cannot run babeltrace2 (%s): %r" % (BT2, e)}
    with p:
        for line in p.stdout:
            scanned += 1
            if scanned > MAX_SCAN:
                break
            m = _EVENT_RE.search(line)
            if not m or not ev_re.search(m.group(1)):
                continue
            if contains and contains not in line:
                continue
            if procname:
                pm = _PROC_RE.search(line)
                if not pm or pm.group(1) != procname:
                    continue
            lines.append(line.rstrip()[:400])
            if len(lines) >= n:
                break
        p.kill()
    return {
        "event_pattern": event, "range": [begin, end], "clock": "UTC",
        "filters": {"procname": procname, "contains": contains},
        "returned": len(lines), "lines": lines,
        "note": ("These are the first matching lines in the range, not a random sample, and "
                 "not a count. Use query_ctf if you want to know how many there were."),
    }


def ctf_procdiff(run_dir: str, begin_a: str, end_a: str, begin_b: str, end_b: str,
                 event: str = ".", top: int = 20, ctf_subdir: str = "kernel/kernel") -> dict:
    """Compare WHICH PROCESSES are active in two time ranges you choose.

    The pilot showed why this is needed. Sixty runs looked for a change in how MANY events
    were happening, and 52 of them landed on the recovery rather than the fault, because the
    injected co-tenant raised no totals - it was simply a process that had not been there
    before. Volume answers "how much"; this answers "who", and for a whole class of faults
    only the second one moves.

    Rates, not raw counts, so ranges of different lengths compare honestly. Ground truth is
    not consulted: both ranges are the agent's choice, and naming one of them "baseline" is
    the agent's claim to defend, not something this tool knows.
    """
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}
    idx = _index_for(run_dir)
    if idx is None:
        return {"error": "no count index for this run, so a process diff would be a guess. "
                         "Build one with blueprints/lib/build_ctf_index.py."}

    a0, a1 = _secs_safe(begin_a), _secs_safe(end_a)
    b0, b1 = _secs_safe(begin_b), _secs_safe(end_b)
    if None in (a0, a1, b0, b1) or a1 <= a0 or b1 <= b0:
        return {"error": "need two ranges as HH:MM:SS, each with end after begin"}
    top = max(1, min(int(top), 60))

    ca, cb = Counter(), Counter()
    for bt, _ev, proc, n in _scan_index(idx, ev_re=ev_re):
        if a0 <= bt < a1:
            ca[proc] += n
        if b0 <= bt < b1:
            cb[proc] += n
    if not ca and not cb:
        return {"event_pattern": event, "matched": 0,
                "note": "no events of this pattern in either range - check the pattern"}

    da, db = a1 - a0, b1 - b0
    rows = []
    for proc in set(ca) | set(cb):
        ra, rb = ca[proc] / da, cb[proc] / db
        rows.append({"procname": proc, "kernel_thread": _is_kthread(proc),
                     "rate_a": round(ra, 1), "rate_b": round(rb, 1),
                     "delta_per_s": round(rb - ra, 1),
                     "times": (round(rb / ra, 2) if ra > 0 else None)})

    only_b = sorted([r for r in rows if r["rate_a"] == 0 and r["rate_b"] > 0],
                    key=lambda r: -r["rate_b"])
    only_a = sorted([r for r in rows if r["rate_b"] == 0 and r["rate_a"] > 0],
                    key=lambda r: -r["rate_a"])
    movers = sorted([r for r in rows if r["rate_a"] > 0 and r["rate_b"] > 0],
                    key=lambda r: -abs(r["delta_per_s"]))

    return {
        "event_pattern": event, "clock": "UTC",
        "range_a": [begin_a, end_a], "range_b": [begin_b, end_b],
        "total_rate_a": round(sum(ca.values()) / da, 1),
        "total_rate_b": round(sum(cb.values()) / db, 1),
        "only_in_b": only_b[:top],
        "only_in_a": only_a[:top],
        "biggest_changes": movers[:top],
        "source": "count index (both ranges read end to end)",
        "how_to_read": (
            "only_in_b is a process active in B and completely absent from A; only_in_a is the "
            "reverse. Those two lists are the point of this tool. biggest_changes is for "
            "processes present in both, and is weaker evidence: a process that merely does "
            "more work may be a victim of the culprit rather than the culprit. Compare "
            "total_rate_a against total_rate_b before reading anything into a single process - "
            "if the totals moved as much as your candidate did, the whole workload shifted. "
            "kernel_thread=true marks an operating-system thread (swapper, kworker, ksoftirqd, "
            "jbd2 and so on) rather than a deployed program; they appear and vanish as the "
            "kernel schedules its own work, so they are rarely a cause though they can be a "
            "symptom."),
    }


# Kernel threads, not workloads. swapper is the idle task, kworker/kthreadd are the kernel's
# own worker pool, ksoftirqd/migration/rcu/watchdog are per-CPU housekeeping, jbd2 is the
# filesystem journal. None of them is a program somebody deployed, and an SRE reading a trace
# knows that at a glance. Flagging them is not doing the analysis - it is supplying the OS
# knowledge the agent is not being tested on. The first run with ctf_proclife blamed
# `kworker/u48:8`, which is a kernel worker doing 8,569 events, over `stress-ng-cpu` doing
# 1.68 million.
_KTHREAD_RE = re.compile(r"^(swapper/|kworker/|ksoftirqd/|migration/|rcu_|rcuo|watchdog/|"
                         r"kthreadd$|irq/|jbd2/|kcompactd|kswapd|khugepaged|ktlsd|"
                         r"idle_inject/|cpuhp/|netns$|kdevtmpfs$|writeback$|kblockd)")


def _is_kthread(proc: str) -> bool:
    return bool(_KTHREAD_RE.match(proc or ""))


def ctf_proclife(run_dir: str, min_events: int = 1000, event: str = ".",
                 ctf_subdir: str = "kernel/kernel") -> dict:
    """When each process FIRST and LAST appears across the whole recording.

    A process that starts or stops part-way through the recording is a change point that no
    event-count series will show you. Anything whose life covers the full span was there the
    whole time and did not arrive with the problem.

    This is raw arrival and departure, nothing more. It does not say which of them matters,
    or whether any of them is a fault - a recording normally contains short-lived processes
    that are perfectly ordinary.
    """
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}
    idx = _index_for(run_dir)
    if idx is None:
        return {"error": "no count index for this run. Build one with "
                         "blueprints/lib/build_ctf_index.py."}

    first: dict = {}
    last: dict = {}
    tot: Counter = Counter()
    lo = hi = None
    for bt, _ev, proc, n in _scan_index(idx, ev_re=ev_re):
        lo = bt if lo is None else min(lo, bt)
        hi = bt if hi is None else max(hi, bt)
        tot[proc] += n
        if proc not in first:
            first[proc] = bt
        last[proc] = bt
    if not tot:
        return {"event_pattern": event, "note": "nothing matched this pattern"}

    span = max(1e-6, hi - lo)
    part, whole = [], []
    for proc, n in tot.items():
        if n < min_events:
            continue
        f, l = first[proc], last[proc]
        row = {"procname": proc, "first_seen": _fmt(f), "last_seen": _fmt(l),
               "alive_s": round(l - f, 1), "events": n,
               "kernel_thread": _is_kthread(proc),
               "covers_pct_of_recording": round(100.0 * (l - f) / span, 1)}
        # 95% rather than 100%: bucket edges and a quiet first or last bucket should not
        # promote a process that ran throughout into the "arrived part-way" list.
        (whole if (l - f) >= 0.95 * span else part).append(row)

    # Busiest first, not earliest first. Sorted by arrival, the eye lands on whatever happened
    # to start soonest, and the first run to use this tool blamed an 8,569-event kernel worker
    # sitting above a 1.68-million-event process. Event count is a plain fact about the row,
    # not a hint about which one matters - a busy process can easily be a victim.
    part.sort(key=lambda r: -r["events"])
    whole.sort(key=lambda r: -r["events"])
    return {
        "event_pattern": event, "clock": "UTC",
        "recording": [_fmt(lo), _fmt(hi)],
        "min_events": min_events,
        "present_for_only_part_of_the_recording": part,
        "present_throughout": [r["procname"] for r in whole],
        "source": "count index (every event in the recording)",
        "how_to_read": (
            "The first list is where a change of WHO is visible, ordered by how many events "
            "each process produced - that is a fact about the row, not a ranking of blame, "
            "since a busy process can be a victim. A process that appears at one time and "
            "stops at another marks two boundaries, and those are candidate incident edges. "
            "kernel_thread=true means it is part of the operating system (swapper, kworker, "
            "ksoftirqd, jbd2 and so on), not a program anyone deployed: those come and go as "
            "the kernel schedules its own work and are rarely the cause, though they can be a "
            "symptom. Plenty of short-lived user processes are routine too, so confirm what a "
            "candidate was actually doing with query_ctf and ctf_lines before believing it. "
            "Raise min_events to hide noise. A process in the second list ran the whole time "
            "and cannot be something that arrived."),
    }


PROCDIFF_DEF = {
    "name": "ctf_procdiff",
    "description": (
        "Compare WHICH PROCESSES are active in two time ranges you choose, by rate so the "
        "ranges need not be the same length. Tells you what is in B but not in A, what is in A "
        "but not in B, and who changed most. Use this when you suspect a period and want to "
        "know what is different about it - counting events tells you how much is happening, "
        "this tells you who is doing it, and they often disagree."),
    "parameters": {"type": "object", "properties": {
        "begin_a": {"type": "string", "description": "range A start 'HH:MM:SS' UTC"},
        "end_a": {"type": "string", "description": "range A end 'HH:MM:SS' UTC"},
        "begin_b": {"type": "string", "description": "range B start 'HH:MM:SS' UTC"},
        "end_b": {"type": "string", "description": "range B end 'HH:MM:SS' UTC"},
        "event": {"type": "string", "description":
                  "event name substring or regex; default '.' means all events"},
        "top": {"type": "integer", "description": "rows per list, 1-60 (default 20)"}},
        "required": ["begin_a", "end_a", "begin_b", "end_b"]},
}

PROCLIFE_DEF = {
    "name": "ctf_proclife",
    "description": (
        "When each process FIRST and LAST appears in the recording. Splits them into those "
        "present for only part of it and those present throughout. A process that arrives or "
        "leaves part-way through marks a boundary that no event-count chart will show you, so "
        "this is usually the fastest way to find candidate incident edges. Short-lived "
        "processes are often routine - confirm before believing one."),
    "parameters": {"type": "object", "properties": {
        "min_events": {"type": "integer", "description":
                       "ignore processes with fewer events than this (default 1000); raise it "
                       "to cut noise"},
        "event": {"type": "string", "description":
                  "event name substring or regex; default '.' means all events"}},
        "required": []},
}


# --- fallbacks: no index for this run, so read the trace under a cap -----------------------
# Kept so the tools still work on a bundle nobody has indexed. Both are honest about the cap,
# because a silent partial answer is worse than an error: the agent treats a lower bound as a
# count. See the note at the top of this file.

def _timeline_from_trace(run_dir: str, event: str, buckets: int,
                         procname: str | None, ctf_subdir: str) -> dict:
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    ev_re = re.compile(event)
    stamps, scanned, truncated = [], 0, False
    try:
        p = subprocess.Popen([BT2] + GMT + [ctf], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1 << 20)
    except OSError as e:
        return {"error": "cannot run babeltrace2 (%s): %r" % (BT2, e)}
    with p:
        for line in p.stdout:
            scanned += 1
            if scanned > MAX_SCAN * 5:
                truncated = True
                break
            m = _EVENT_RE.search(line)
            if not m or not ev_re.search(m.group(1)):
                continue
            if procname:
                pm = _PROC_RE.search(line)
                if not pm or pm.group(1) != procname:
                    continue
            t = _clock(line)
            if t is not None:
                stamps.append(t)
        p.kill()
    if not stamps:
        return {"event_pattern": event, "matched": 0, "source": "raw trace (no index)",
                "note": "no events matched - check the pattern, or the tracepoint was off"}
    lo, hi = min(stamps), max(stamps)
    width = max(1e-6, (hi - lo) / buckets)
    counts = [0] * buckets
    for t in stamps:
        counts[min(buckets - 1, int((t - lo) / width))] += 1
    peak = max(counts)
    out = {
        "event_pattern": event, "procname": procname, "clock": "UTC",
        "span_covered": [_fmt(lo), _fmt(hi)], "bucket_width_s": round(width, 3),
        "matched": len(stamps), "events_scanned": scanned, "truncated": truncated,
        "source": "raw trace under a scan cap (no index for this run)",
        "series": [{"t": _fmt(lo + i * width), "n": c,
                    "bar": "#" * int(round(20 * c / peak)) if peak else ""}
                   for i, c in enumerate(counts)],
    }
    if truncated:
        out["WARNING"] = (
            "SCAN CAP HIT. This series covers only %s to %s, NOT the whole recording. Compare "
            "against ctf_timespan: if that span is longer, the rest was never examined and you "
            "must not conclude anything about it." % (_fmt(lo), _fmt(hi)))
    return out


def _query_from_trace(run_dir: str, event: str, begin, end, sample: int,
                      procname, contains, ctf_subdir: str) -> dict:
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    ev_re = re.compile(event)
    sample = max(0, min(int(sample), MAX_SAMPLE))
    cmd = [BT2] + GMT + [ctf]
    if begin:
        cmd += ["--begin", begin]
    if end:
        cmd += ["--end", end]
    by_event, by_proc = Counter(), Counter()
    lines, scanned, truncated = [], 0, False
    first_t = last_t = None
    scan_first = scan_last_line = None
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, bufsize=1 << 20)
    except OSError as e:
        return {"error": "cannot run babeltrace2 (%s): %r" % (BT2, e)}
    with p:
        for line in p.stdout:
            scanned += 1
            if scanned > MAX_SCAN:
                truncated = True
                break
            if scan_first is None:
                scan_first = _clock(line)
            scan_last_line = line
            m = _EVENT_RE.search(line)
            if not m or not ev_re.search(m.group(1)):
                continue
            if contains and contains not in line:
                continue
            pm = _PROC_RE.search(line)
            proc = pm.group(1) if pm else "?"
            if procname and proc != procname:
                continue
            t = _clock(line)
            if t is not None:
                first_t = t if first_t is None else first_t
                last_t = t
            by_event[m.group(1)] += 1
            by_proc[proc] += 1
            if len(lines) < sample:
                lines.append(line.rstrip()[:400])
        p.kill()

    dur = (last_t - first_t) if (first_t is not None and last_t is not None) else None
    total = sum(by_event.values())
    scan_last = _clock(scan_last_line) if scan_last_line else None
    scan_span = (scan_last - scan_first) if (scan_first is not None and scan_last is not None) else None
    want = None
    if begin and end:
        b, e = _secs_safe(begin), _secs_safe(end)
        if b is not None and e is not None and e > b:
            want = e - b
    cover = round(100.0 * scan_span / want, 1) if (scan_span is not None and want) else None
    if truncated and cover is not None:
        note = ("scan cap of %d events hit: you asked for %.1f s and only the first %.1f s "
                "(%.1f%%) was read. Counts are a LOWER BOUND. Compare rate_per_s between "
                "ranges rather than counts, and remember a zero means 'not in the part I "
                "read', not 'absent'." % (MAX_SCAN, want, scan_span, cover))
    elif truncated:
        note = ("scan cap of %d events hit - counts are a LOWER BOUND and the range was not "
                "fully read." % MAX_SCAN)
    else:
        note = "range fully read"
    return {
        "event_pattern": event,
        "range_requested": [begin, end],
        "range_actually_read": [_fmt(scan_first) if scan_first is not None else None,
                                _fmt(scan_last) if scan_last is not None else None],
        "coverage_pct_of_requested": cover,
        "filters": {"procname": procname, "contains": contains},
        "matched": total,
        "rate_per_s": round(total / dur, 2) if dur and dur > 0 else None,
        "events_scanned": scanned, "truncated": truncated, "note": note,
        "source": "raw trace under a scan cap (no index for this run)",
        "by_event": dict(by_event.most_common(15)),
        "top_procnames": dict(by_proc.most_common(TOP_PROCS)),
        "sample": lines,
    }



TIMESPAN_DEF = {
    "name": "ctf_timespan",
    "description": ("Start time, end time and duration of the whole recording, in UTC, read "
                    "from the collection metadata the bundle carries. Call this first to "
                    "orient: every range you ask for later must sit inside it. It does NOT "
                    "tell you where any incident is - finding that is your job."),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

TIMELINE_DEF = {
    "name": "ctf_timeline",
    "description": ("Count one kernel event across the WHOLE trace, bucketed in time, with a "
                    "little bar chart. This is how you FIND when something happened: look for "
                    "a sustained step up or down in the series. Confirm any candidate against "
                    "a second, unrelated event - a step in everything usually means the "
                    "workload changed rather than the system misbehaving."),
    "parameters": {"type": "object", "properties": {
        "event": {"type": "string", "description":
                  "event name substring or regex, e.g. 'sched_switch', 'sched_wakeup', "
                  "'block_rq_issue', 'net_dev_xmit', 'syscall_entry_futex'"},
        "buckets": {"type": "integer", "description": "time buckets, 5-120 (default 30)"},
        "procname": {"type": "string", "description": "optional exact procname filter"}},
        "required": ["event"]},
}

TOOL_DEF = {
    "name": "query_ctf",
    "description": (
        "Count one kernel event over a time range YOU choose, and see which processes produced "
        "it. Any tracepoint the kernel recorded is available. begin/end are UTC clock strings "
        "like '13:12:30'; omit both for the whole recording. Exact over the whole range you "
        "name - not a sample of it. Counts are meaningless alone: compare a range you suspect "
        "against a range you believe is quiet, and be able to say why you chose each. Set "
        "`buckets` to see the range broken down over time."),
    "parameters": {"type": "object", "properties": {
        "event": {"type": "string", "description": "event name substring or regex"},
        "begin": {"type": "string", "description": "start clock 'HH:MM:SS' UTC (optional)"},
        "end": {"type": "string", "description": "end clock 'HH:MM:SS' UTC (optional)"},
        "procname": {"type": "string", "description": "optional exact procname filter"},
        "buckets": {"type": "integer", "description":
                    "optional: split the range into this many time buckets, 5-120"}},
        "required": ["event"]},
}

LINES_DEF = {
    "name": "ctf_lines",
    "description": (
        "Read real event lines, with all their fields, straight from the raw trace. Use it to "
        "see WHAT an event actually contains once query_ctf has told you where to look - the "
        "processes involved, the CPU, the prev/next task, the syscall arguments. Narrow ranges "
        "only (at most %d s) and a few lines at a time." % int(MAX_LINES_RANGE_S)),
    "parameters": {"type": "object", "properties": {
        "event": {"type": "string", "description": "event name substring or regex"},
        "begin": {"type": "string", "description": "start clock 'HH:MM:SS' UTC (required)"},
        "end": {"type": "string", "description": "end clock 'HH:MM:SS' UTC (required)"},
        "n": {"type": "integer", "description": "lines to return, 1-%d (default 10)" % MAX_SAMPLE},
        "procname": {"type": "string", "description": "optional exact procname filter"},
        "contains": {"type": "string", "description": "optional substring the line must contain"}},
        "required": ["event", "begin", "end"]},
}



if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--op", default="timespan", choices=["timespan", "timeline", "query"])
    ap.add_argument("--event", default="sched_switch")
    ap.add_argument("--begin")
    ap.add_argument("--end")
    ap.add_argument("--buckets", type=int, default=30)
    ap.add_argument("--procname")
    a = ap.parse_args()
    if a.op == "timespan":
        r = ctf_timespan(a.run_dir)
    elif a.op == "timeline":
        r = ctf_timeline(a.run_dir, a.event, a.buckets, a.procname)
    else:
        r = query_ctf(a.run_dir, a.event, a.begin, a.end, 5, a.procname)
    print(json.dumps(r, indent=1)[:5000])
