#!/usr/bin/env python3
# log_errors.py - find error messages in container logs that became much more frequent.
#
# Reads the per-container log files of a run (each line starts with the time Docker wrote it),
# keeps the lines that look like errors, turns each into a template (numbers, ids and hex
# replaced), and compares the rate of every template in a baseline window and a suspect window.
#
# Usage:
#   python3 log_errors.py <logs_dir> <suspect_start_utc> <window_seconds>
#   python3 log_errors.py --selftest
#
#   suspect_start_utc: e.g. 2026-11-26T20:15:13Z; the baseline is the same length just before it.
import glob
import os
import re
import sys
import calendar
import time
from collections import defaultdict

MIN_RATE = 1.0         # lines per second of one template in one container in the suspect window
MIN_RISE = 10.0        # ... and this many times its baseline rate
# Bars set before the first run on labelled data (26-11-2026) and not fitted to it.
ERROR = re.compile(r'error|err=|exception|unauthori[sz]ed|forbidden|denied|fail|refused|timeout|timed out|invalid|\b[45]\d\d\b', re.I)
re_ts = re.compile(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)')
# Lines that are not messages of the program: the Java agents print every finished span to the
# log (the UST relay reads them). They carry status codes and words like "error" in span names.
# Found after run 1 (26-11-2026): they made the reversed check fire in all 4 families.
NOT_MESSAGES = ("LoggingSpanExporter", "io.opentelemetry.exporter")


def template(msg):
    msg = re.sub(r'\b\d{4}-\d\d-\d\dT[\d:.]+Z?\b', '<t>', msg)
    msg = re.sub(r'\b[0-9a-f]{12,}\b', '<id>', msg)
    msg = re.sub(r'\d+(\.\d+)?', '<n>', msg)
    return msg[:160]


def read(logs_dir, start, secs):
    t0 = calendar.timegm(time.strptime(start[:19], "%Y-%m-%dT%H:%M:%S"))
    cnt = defaultdict(lambda: [0, 0])            # (container, template) -> [baseline, suspect]
    sample = {}
    first = None
    for f in sorted(glob.glob(os.path.join(logs_dir, "*.log"))):
        cont = os.path.basename(f)[:-4]
        for line in open(f, errors="replace"):
            m = re_ts.match(line)
            if not m:
                continue
            t = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
            first = t if first is None else min(first, t)
            w = 0 if t0 - secs <= t < t0 else 1 if t0 <= t < t0 + secs else None
            if w is None:
                continue
            msg = line.split(" ", 1)[1].strip() if " " in line else ""
            if not ERROR.search(msg) or any(x in msg for x in NOT_MESSAGES):
                continue
            k = (cont, template(msg))
            cnt[k][w] += 1
            sample.setdefault(k, msg[:200])
    covered = first is not None and first <= t0 - secs + 1
    return cnt, sample, covered


def report(cnt, sample, secs, covered=True):
    if not covered:
        return ["VERDICT: NOT JUDGED (the logs start after the beginning of the baseline window, so there is no full baseline)"]
    rows = sorted(cnt.items(), key=lambda kv: -(kv[1][1] - kv[1][0]))
    out = [f"Error-like log lines per container and message, {secs:.0f} s before and from the suspect time (largest rise first)",
           f"  {'container':<34} {'before':>7} {'now':>7}  message"]
    for (c, tpl), (b, n) in rows[:10]:
        out.append(f"  {c:<34} {b:>7} {n:>7}  {tpl[:90]}")
    hits = 0
    for (c, tpl), (b, n) in rows:
        if n / secs < MIN_RATE or n < MIN_RISE * max(b, 1):
            continue
        out.append(f"VERDICT: A NEW STREAM OF ERRORS: {c} logged {n} lines of one error message in {secs:.0f} s "
                   f"({n / secs:.1f} per second), {b} before: \"{sample[(c, tpl)][:140]}\"")
        hits += 1
        if hits >= 3:
            break
    if not hits:
        top = rows[0] if rows else None
        why = (f"largest rise: {top[0][0]} {top[1][0]} -> {top[1][1]}" if top else "no error-like line")
        out.append(f"VERDICT: NO NEW STREAM OF ERRORS ({why}; the bars are {MIN_RATE} per second and {MIN_RISE:.0f}x the baseline)")
    return out


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "docker-compose_user_1.log"), "w") as f:
        for s in range(120):
            ts = "2026-11-26T20:%02d:%02d.000Z" % (14 + s // 60, s % 60)
            f.write(f"{ts} ts=x caller=middlewares.go:75 method=GetUsers id=6b089335ee11cb0001692d41 result=1 took=270µs\n")
            if s >= 60:
                for k in range(15):
                    f.write(f"{ts} ts=2026-11-26T20:15:{s % 60:02d}Z caller=server.go:94 err=Unauthorized\n")
            if s % 30 == 0:
                f.write(f"{ts} level=warn msg=\"slow query took 2{s}ms\"\n")
    cnt, sample, cov = read(d, "2026-11-26T20:15:00Z", 60)
    out = "\n".join(report(cnt, sample, 60, cov))
    assert "A NEW STREAM OF ERRORS: docker-compose_user_1 logged 900 lines of one error message in 60 s (15.0 per second), 0 before" in out, out
    assert out.count("VERDICT") == 1, out
    cnt, sample, cov = read(d, "2026-11-26T20:14:30Z", 30)
    assert "NO NEW STREAM OF ERRORS" in "\n".join(report(cnt, sample, 30, cov))
    cnt, sample, cov = read(d, "2026-11-26T20:14:20Z", 60)
    assert "NOT JUDGED" in "\n".join(report(cnt, sample, 60, cov))
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: log_errors.py <logs_dir> <suspect_start_utc> <window_seconds>", file=sys.stderr)
        sys.exit(1)
    secs = float(sys.argv[3])
    cnt, sample, cov = read(sys.argv[1], sys.argv[2], secs)
    print("\n".join(report(cnt, sample, secs, cov)))
