#!/usr/bin/env python3
"""
log_window.py - what changed in the application logs between a baseline slice and a fault slice?

Usage:
    python3 log_window.py <run.logidx.json.gz> <fault_start> <secs> --baseline <base_start> <secs>
                          [--entity NAME] [--top N]

    <fault_start>, <base_start>   HH:MM:SS (UTC, the trace clock), the same times the blueprint's
                                  kernel slices use, so both tools look at the same seconds

Input: a log index built by `python -m logkit.build`. Standard library only; logidx.py and
logsig.py must be in the same folder.

What counts as a change is defined once, in logsig.py: a new warning-or-worse template, a rise
in the share of warning lines, or a rise in a method's median request time. A fall in the line
rate is printed as a NOTE only.

Output: one row per entity, the new templates (E1, E2, ...), then verdict lines:

    LOG DIFF: <entity> (<kind>): <what changed>     one per changed entity, earliest first
    NO LOG DIFF: ...                                nothing changed in any entity
    LOG WINDOW OUTSIDE LOGS: ...                    the slices are not covered by the logs
    LOG CLOCK NOT ALIGNED: ...                      the log clock cannot be compared with the trace
    NO LOGS: ...

A LOG DIFF does not say which entity is at fault: a caller logs the timeouts of the service it
waits on. NO LOG DIFF does not say nothing is wrong. The kernel check decides.

Self-test:  python -m pytest Blueprint/logkit/tests
"""
from __future__ import annotations

import argparse
import sys

try:
    from . import logidx as L
    from . import logsig as G
except ImportError:                      # run as a copied script
    import logidx as L
    import logsig as G

TOP = 12


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="What changed in the logs between two slices?")
    ap.add_argument("index", help="<run>.logidx.json.gz")
    ap.add_argument("fault_start", help="HH:MM:SS")
    ap.add_argument("fault_secs", type=float)
    ap.add_argument("--baseline", nargs=2, required=True, metavar=("BASE_START", "SECS"),
                    help="a slice before the change; required, as for the kernel tools")
    ap.add_argument("--entity", help="only this entity")
    ap.add_argument("--top", type=int, default=TOP)
    a = ap.parse_args(argv)
    idx = L.load(a.index)

    if not idx.lines or idx.t0 is None:
        print("NO LOGS: the index of %s holds no log lines." % idx.run)
        return 0
    if not idx.clock_aligned:
        print("LOG CLOCK NOT ALIGNED: the logs of %s carry their own clock, so slices on the "
              "trace clock cannot be matched to them. Use log_onset.py for the log's own times."
              % idx.run)
        return 0
    try:
        fa = L.resolve_time(a.fault_start, idx.t0)
        ba = L.resolve_time(a.baseline[0], idx.t0)
        bsecs = float(a.baseline[1])
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    win, base = (fa, fa + a.fault_secs), (ba, ba + bsecs)
    for name, (x, y) in (("fault", win), ("baseline", base)):
        if y <= idx.t0 or x >= idx.t1:
            print("LOG WINDOW OUTSIDE LOGS: the %s slice %s to %s is outside the logs (%s to %s)."
                  % (name, L.hms(x), L.hms(y), L.hms(idx.t0), L.hms(idx.t1)))
            return 0
    if base[1] > win[0]:
        print("NOTE: the baseline ends after the fault slice starts; a change may be hidden.")

    ents = [e for e in idx.entities.values() if e.lines and (not a.entity or e.name == a.entity)]
    if a.entity and not ents:
        print("error: no entity %r; known: %s" % (a.entity, ", ".join(sorted(idx.entities))),
              file=sys.stderr)
        return 2
    diffs = [G.diff(e, base, win) for e in ents]

    print("log index %s: baseline %s +%.0f s, fault %s +%.0f s" % (
        idx.run, L.hms(base[0]), bsecs, L.hms(win[0]), a.fault_secs))
    print()
    print("%-16s %-10s %14s %14s %4s  %s" % ("entity", "kind", "lines/s", "warnings/s", "new",
                                             "latency (largest change)"))
    for d in sorted(diffs, key=lambda d: d.entity):
        lat = ""
        if d.latency:
            c = max(d.latency, key=lambda c: c.win_ms / c.base_ms)
            lat = "%s p50 %s -> %s ms" % (c.method, G._ms(c.base_ms), G._ms(c.win_ms))
        print("%-16s %-10s %6.1f -> %-5.1f %6.1f -> %-5.1f %4d  %s" % (
            d.entity[:16], d.kind, d.base_lines_s, d.win_lines_s, d.base_warn_s, d.win_warn_s,
            len(d.new), lat))
    print()

    new = sorted(((t, d.entity) for d in diffs for t in d.new), key=lambda x: -x[0].level)
    for i, (t, ent) in enumerate(sorted(new[:a.top], key=lambda x: x[0].first), 1):
        print("E%d  %s  %-14s x%-5d %s%s" % (i, L.hms(t.first), ent[:14], t.count_in(*win),
                                            G._quote(t.example, 140),
                                            "  (generic)" if t.generic else ""))
    if new:
        print()

    drops = [d for d in diffs if d.drop]
    if drops:
        print("NOTE: line rate fell in %s; a load phase ending looks the same, so this is not "
              "counted as a change." % ", ".join("%s %.0f/s -> %.0f/s" % (d.entity, d.base_lines_s,
                                                                         d.win_lines_s)
                                                 for d in drops))
    changed = [d for d in diffs if d.changed]
    if not changed:
        print("NO LOG DIFF: no new warning or error, no rise in warnings and no latency rise in "
              "%d entities between the baseline and the fault slice. The logs show nothing; that "
              "does not mean the system is healthy." % len(diffs))
        return 0

    def first_time(d):
        return min([t.first for t in d.new] or [win[0]])

    for d in sorted(changed, key=first_time):
        print("LOG DIFF: %s (%s): %s" % (d.entity, d.kind, d.describe()))
    print("NOTE: an entity that logs a change is often a caller of the faulty one; the kernel "
          "check decides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
