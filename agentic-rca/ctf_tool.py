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

MAX_SAMPLE = 40
MAX_SCAN = 400000
_TIME_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d+)\]")
_EVENT_RE = re.compile(r"\]\s+(?:\(\+[^)]*\)\s+)?\S+\s+([a-zA-Z0-9_]+):")
_PROC_RE = re.compile(r'procname\s*=\s*"([^"]*)"')


def _secs(hhmmss: str) -> float:
    h, m, s = hhmmss.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _clock(line: str):
    m = _TIME_RE.match(line)
    if not m:
        return None
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + float("0." + m.group(4)))


def _fmt(sec: float) -> str:
    sec = max(0.0, sec)
    return "%02d:%02d:%06.3f" % (int(sec) // 3600 % 24, int(sec) // 60 % 60, sec % 60)


def ctf_timespan(run_dir: str, ctf_subdir: str = "kernel/kernel") -> dict:
    """First and last timestamp in the trace, read FROM THE TRACE. No ground truth involved.

    This is the agent's only free orientation: how long the recording is. Where anything
    interesting sits inside it is for the agent to find.
    """
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    out = {}
    try:
        p = subprocess.run([BT2, ctf, "--clock-seconds"], capture_output=True, text=True,
                           timeout=25)
        first = p.stdout[:400].splitlines()
        out["first_line"] = first[0][:200] if first else None
    except Exception:                                                    # noqa: BLE001
        pass
    # head/tail without decoding twice: bt2 streams in order, so first and last lines suffice
    try:
        p = subprocess.Popen([BT2, ctf], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, bufsize=1 << 20)
        first_t = last_t = None
        n = 0
        with p:
            for line in p.stdout:
                t = _clock(line)
                if t is None:
                    continue
                n += 1
                if first_t is None:
                    first_t = t
                last_t = t
                if n > 4_000_000:                    # safety, not expected to trigger
                    break
            p.kill()
        return {"begin": _fmt(first_t) if first_t else None,
                "end": _fmt(last_t) if last_t else None,
                "duration_s": round(last_t - first_t, 3) if (first_t and last_t) else None,
                "events_seen": n,
                "note": ("This is the whole recording. Nothing here says where an incident is - "
                         "use ctf_timeline to look for a change, then query_ctf to inspect it.")}
    except OSError as e:
        return {"error": "cannot run babeltrace2 (%s): %r" % (BT2, e)}


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
        p = subprocess.Popen([BT2, ctf], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, bufsize=1 << 20)
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
    return {
        "event_pattern": event, "procname": procname,
        "span": [_fmt(lo), _fmt(hi)], "bucket_width_s": round(width, 3),
        "matched": len(stamps), "events_scanned": scanned, "truncated": truncated,
        "series": series,
        "how_to_read": ("Each row is one time bucket and its event count. A sustained step up "
                        "or down partway through is a candidate change point. Confirm it "
                        "against a second, unrelated event before believing it - a step in "
                        "every event type usually means the workload changed, not the system."),
    }


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

    cmd = [BT2, ctf]
    if begin:
        cmd += ["--begin", begin]
    if end:
        cmd += ["--end", end]

    by_event, by_proc = Counter(), Counter()
    lines, scanned, truncated = [], 0, False
    first_t = last_t = None
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
    return {
        "event_pattern": event,
        "range_requested": [begin, end],
        "range_matched": [_fmt(first_t) if first_t is not None else None,
                          _fmt(last_t) if last_t is not None else None],
        "filters": {"procname": procname, "contains": contains},
        "matched": total,
        "rate_per_s": round(total / dur, 2) if dur and dur > 0 else None,
        "events_scanned": scanned,
        "truncated": truncated,
        "note": ("scan cap of %d hit - counts are a LOWER BOUND and the range was not fully "
                 "read. Narrow the range or the pattern." % MAX_SCAN) if truncated else
                "range fully read",
        "by_event": dict(by_event.most_common(15)),
        "top_procnames": dict(by_proc.most_common(15)),
        "sample": lines,
        "how_to_compare": ("A count on its own means nothing. Compare rate_per_s against "
                           "another range of this same trace that you have reason to believe "
                           "is quiet, and say which range you used and why."),
    }


TIMESPAN_DEF = {
    "name": "ctf_timespan",
    "description": ("Start time, end time and duration of the raw kernel trace, read from the "
                    "trace itself. Call this first to orient. It does NOT tell you where any "
                    "incident is - finding that is your job."),
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
