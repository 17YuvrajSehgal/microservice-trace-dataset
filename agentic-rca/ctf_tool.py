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
        "source": "meta/ cgroup tick snapshots written during collection",
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
    """
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}
    buckets = max(5, min(int(buckets), 120))

    stamps = []
    scanned = 0
    truncated = False
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
        return {"event_pattern": event, "matched": 0,
                "note": "no events matched - check the pattern, or this tracepoint was not enabled"}
    lo, hi = min(stamps), max(stamps)
    width = max(1e-6, (hi - lo) / buckets)
    counts = [0] * buckets
    for t in stamps:
        counts[min(buckets - 1, int((t - lo) / width))] += 1
    peak = max(counts)
    series = [{"t": _fmt(lo + i * width), "n": c,
               "bar": "#" * int(round(20 * c / peak)) if peak else ""}
              for i, c in enumerate(counts)]
    out = {
        "event_pattern": event, "procname": procname, "clock": "UTC",
        "span_covered": [_fmt(lo), _fmt(hi)], "bucket_width_s": round(width, 3),
        "matched": len(stamps), "events_scanned": scanned, "truncated": truncated,
        "series": series,
        "how_to_read": ("Each row is one time bucket and its event count. A sustained step up "
                        "or down partway through is a candidate change point. Confirm it "
                        "against a second, unrelated event before believing it - a step in "
                        "every event type usually means the workload changed, not the system."),
    }
    # A capped scan covers only the START of the recording, but the series still renders as a
    # full-width chart. Left unsaid, "no clearly isolated step" would mean "I did not look at
    # most of it" - which is how a partial read turns into a wrong conclusion.
    if truncated:
        out["WARNING"] = (
            "SCAN CAP HIT. This series covers only %s to %s, NOT the whole recording. Compare "
            "against ctf_timespan: if that span is longer, the rest of the trace was never "
            "examined and you must not conclude anything about it. Narrow with procname, or "
            "sweep later ranges explicitly with query_ctf." % (_fmt(lo), _fmt(hi)))
    return out


def query_ctf(run_dir: str, event: str, begin: str | None = None, end: str | None = None,
              sample: int = 10, procname: str | None = None, contains: str | None = None,
              ctf_subdir: str = "kernel/kernel") -> dict:
    """Read the raw trace for one event pattern over a time range THE AGENT chooses.

    begin/end are clock strings like '03:37:32' (HH:MM:SS[.frac]). Omit both to read the whole
    trace, subject to the scan cap. There are no named windows: naming one would require
    knowing when the incident was, which is the thing being asked.
    """
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    sample = max(0, min(int(sample), MAX_SAMPLE))
    try:
        ev_re = re.compile(event)
    except re.error as e:
        return {"error": "bad event pattern: %s" % e}

    cmd = [BT2] + GMT + [ctf]
    if begin:
        cmd += ["--begin", begin]
    if end:
        cmd += ["--end", end]

    by_event, by_proc = Counter(), Counter()
    lines, scanned, truncated = [], 0, False
    first_t = last_t = None
    # The scan's OWN span, which is not the matched events' span. If the pattern is rare
    # the two differ a lot, and it is the scan span that says how much of the requested
    # range was actually read. Clock-parsed on the first and last line only, not all of
    # them - at 400k lines a per-line regex is not free.
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

    # How much of what was ASKED FOR did we actually read? The first version reported only
    # `truncated: true`, which understates it badly: the agent asked for 20 s, got 0.3 s, and
    # went on comparing windows as if it had them. Say the number.
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
                "(%.1f%%) was read. Raw counts are a LOWER BOUND for the range you named. "
                "Asking for a shorter range does NOT help - babeltrace decodes from the start "
                "of the trace either way. Compare rate_per_s between ranges instead of counts, "
                "and remember a zero here means 'not in the part I read', not 'absent'."
                % (MAX_SCAN, want, scan_span, cover))
    elif truncated:
        note = ("scan cap of %d events hit - counts are a LOWER BOUND and the range was not "
                "fully read. Compare rate_per_s between ranges rather than raw counts; a zero "
                "means 'not in the part I read', not 'absent'." % MAX_SCAN)
    else:
        note = "range fully read"
    return {
        "event_pattern": event,
        "range_requested": [begin, end],
        "range_matched": [_fmt(first_t) if first_t is not None else None,
                          _fmt(last_t) if last_t is not None else None],
        "filters": {"procname": procname, "contains": contains},
        "matched": total,
        "rate_per_s": round(total / dur, 2) if dur and dur > 0 else None,
        "events_scanned": scanned,
        "range_actually_read": [_fmt(scan_first) if scan_first is not None else None,
                                _fmt(scan_last) if scan_last is not None else None],
        "coverage_pct_of_requested": cover,
        "truncated": truncated,
        "note": note,
        "by_event": dict(by_event.most_common(15)),
        "top_procnames": dict(by_proc.most_common(15)),
        "sample": lines,
        "how_to_compare": ("A count on its own means nothing. Compare rate_per_s against "
                           "another range of this same trace that you have reason to believe "
                           "is quiet, and say which range you used and why."),
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
        "Read the RAW LTTng kernel trace for one event type over a time range YOU choose. Any "
        "tracepoint the kernel recorded is available - not only what has been pre-aggregated. "
        "begin/end are clock strings like '03:37:32'; omit both to sweep the whole trace. "
        "Returns counts, a per-second rate, the processes responsible, and real event lines. "
        "Counts are meaningless alone: compare a range you suspect against a range you believe "
        "is quiet, and be able to say why you chose each."),
    "parameters": {"type": "object", "properties": {
        "event": {"type": "string", "description": "event name substring or regex"},
        "begin": {"type": "string", "description": "start clock 'HH:MM:SS' (optional)"},
        "end": {"type": "string", "description": "end clock 'HH:MM:SS' (optional)"},
        "procname": {"type": "string", "description": "optional exact procname filter"},
        "contains": {"type": "string", "description": "optional substring the line must contain"},
        "sample": {"type": "integer", "description":
                   "raw event lines to return, 0-%d (default 10)" % MAX_SAMPLE}},
        "required": ["event"]},
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
