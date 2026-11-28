#!/usr/bin/env python3
# breaker_cause.py - a service's circuit breaker opened: was it a failing dependency, or the
# service turning requests away itself?
#
# A circuit breaker counts failures on a path. After a few in a row it "opens" and fails every
# request on that path at once for a while ("circuit breaker is open"), then lets a few through
# to test. Two very different faults end in the same open breaker:
#   - a dependency fails (a database that does not answer): the service logs the dependency's
#     error (here "database connection error") each time the breaker lets a request through;
#   - the service rejects requests itself (a rate limit): there is no dependency error at all,
#     only the rejections ("too many requests").
# This tool reads the server-side error lines of go-kit services (`caller=server.go ... err="..."`,
# the catalogue here) and counts each error message in a window and in the window before.
#
# CAUTION. "too many requests" is ALSO what the gobreaker library answers while it is half-open
# and more requests come than it lets through. So that message alone does not prove a rate
# limit; the ABSENCE of dependency errors is what the verdict rests on.
#
# Usage:
#   python3 breaker_cause.py <logs_dir> <suspect_start_utc> <window_seconds>
#   python3 breaker_cause.py --selftest
#
#   <logs_dir>  the run's logs/ directory (one Docker log file per container, lines start with
#               an RFC 3339 time)
import datetime
import os
import re
import sys
from collections import Counter

BREAKER = "circuit breaker is open"
SELF = "too many requests"
CLIENT = ("not found",)        # the caller asked for something that does not exist: not a fault here
MIN_BREAKER = 100      # breaker-open answers in the window (and none before)
MIN_DEP = 5            # dependency errors that make it "a dependency fails"
MIN_SELF = 5           # rejections that make it "the service rejects requests itself"
# Bars set 28-11-2026 AFTER looking at the 60 s windows of the 5 code_rate_limit runs (breaker
# about 2,000, rejections 13-20, dependency errors 0) and the 5 mtu_blackhole runs (breaker about
# 11,000, "database connection error" 21 in each, rejections 0-4). Not tested on unseen runs of
# these two families.

re_t = re.compile(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)')
re_err = re.compile(r'caller=server\.go:\d+ err="([^"]*)"')


def read(logs, start, secs):
    t0 = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")
    now, before = {}, {}
    for f in sorted(os.listdir(logs)):
        c, b = Counter(), Counter()
        with open(os.path.join(logs, f), errors="replace") as fh:
            for line in fh:
                e = re_err.search(line)
                m = re_t.match(line) if e else None
                if not m:
                    continue
                d = (datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S") - t0).total_seconds()
                if 0 <= d < secs:
                    c[e.group(1)] += 1
                elif -secs <= d < 0:
                    b[e.group(1)] += 1
        if c or b:
            name = f[:-4] if f.endswith(".log") else f
            now[name], before[name] = c, b
    return now, before


def report(now, before, secs):
    out = [f"Server-side error messages per container, {secs:.0f} s from the suspect time and the {secs:.0f} s before",
           f"  {'container':<34} {'before':>7} {'now':>7}  message"]
    for c in sorted(now, key=lambda k: -sum(now[k].values())):
        for msg, n in now[c].most_common(6):
            out.append(f"  {c:<34} {before[c][msg]:>7} {n:>7}  {msg}")
    hits = 0
    for c in now:
        n, b = now[c], before[c]
        if n[BREAKER] < MIN_BREAKER or b[BREAKER] > 0:
            continue
        dep = {m: k for m, k in n.items() if m not in (BREAKER, SELF) and m not in CLIENT}
        ndep = sum(dep.values())
        if ndep >= MIN_DEP:
            top = max(dep, key=dep.get)
            out.append(f"VERDICT: THE BREAKER OPENED BECAUSE A DEPENDENCY FAILS: {c} answered {n[BREAKER]} requests with "
                       f"'{BREAKER}' in {secs:.0f} s, 0 before, and logged {ndep} dependency errors (most: '{top}', {dep[top]}) - "
                       f"follow the dependency")
            hits += 1
        elif n[SELF] >= MIN_SELF:
            out.append(f"VERDICT: THE BREAKER OPENED ON THE SERVICE'S OWN REJECTIONS: {c} answered {n[BREAKER]} requests with "
                       f"'{BREAKER}' in {secs:.0f} s, 0 before, logged {n[SELF]} '{SELF}' and {ndep} dependency errors - "
                       f"the service turns requests away itself (a rate limit), and its breaker counts those as failures")
            hits += 1
    if not hits:
        top = max(now, key=lambda k: now[k][BREAKER], default=None)
        why = (f"most '{BREAKER}': {now[top][BREAKER]} in {top}, {before[top][BREAKER]} before" if top else "no server-side error lines")
        out.append(f"VERDICT: NO NEW OPEN BREAKER ({why}; the bars are {MIN_BREAKER} breaker answers and none before, then "
                   f"{MIN_DEP} dependency errors or {MIN_SELF} rejections)")
    return out


def selftest():
    import tempfile
    d = tempfile.mkdtemp()

    def write(name, lines):
        with open(os.path.join(d, name), "w") as f:
            f.write("\n".join(lines) + "\n")

    def ln(sec, err):
        t = datetime.datetime(2026, 11, 28, 6, 0, 0) + datetime.timedelta(seconds=sec)
        return f'{t:%Y-%m-%dT%H:%M:%S}.123Z ts=x caller=server.go:110 err="{err}"'

    rl = [ln(s, BREAKER) for s in range(60) for _ in range(30)] + [ln(s, SELF) for s in range(0, 60, 4)] + [ln(-30, "not found")]
    write("docker-compose_catalogue_1.log", rl)
    out = "\n".join(report(*read(d, "2026-11-28T06:00:00Z", 60), 60))
    assert "THE BREAKER OPENED ON THE SERVICE'S OWN REJECTIONS: docker-compose_catalogue_1 answered 1800 requests" in out, out
    assert "logged 15 'too many requests' and 0 dependency errors" in out and out.count("VERDICT") == 1, out
    dep = [ln(s, BREAKER) for s in range(60) for _ in range(30)] + [ln(s, "database connection error") for s in range(0, 60, 3)] + [ln(5, SELF)]
    write("docker-compose_catalogue_1.log", dep)
    out = "\n".join(report(*read(d, "2026-11-28T06:00:00Z", 60), 60))
    assert "THE BREAKER OPENED BECAUSE A DEPENDENCY FAILS: docker-compose_catalogue_1 answered 1800 requests" in out, out
    assert "logged 20 dependency errors (most: 'database connection error', 20)" in out, out
    write("docker-compose_catalogue_1.log", [ln(s, "not found") for s in range(-60, 60)])
    out = "\n".join(report(*read(d, "2026-11-28T06:00:00Z", 60), 60))
    assert "NO NEW OPEN BREAKER (most 'circuit breaker is open': 0" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: breaker_cause.py <logs_dir> <suspect_start_utc> <window_seconds>", file=sys.stderr)
        sys.exit(1)
    print("\n".join(report(*read(sys.argv[1], sys.argv[2], float(sys.argv[3])), float(sys.argv[3]))))
