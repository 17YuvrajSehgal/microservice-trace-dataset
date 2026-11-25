#!/usr/bin/env python3
"""
log_onset.py - when did the application logs first change, and in which entity?

Usage:
    python3 log_onset.py <run.logidx.json.gz> [--top N]

Input: a log index built by `python -m logkit.build`. Standard library only; logidx.py and
logsig.py must be in the same folder.

How it works. The baseline is the start of the run: BASE_S seconds after a short warm-up. The
tool does not ask for a baseline time, so it cannot be handed one that lies inside the fault
(the lesson of the scan tool, METHOD.md section 3). Then, per entity:

    new        a warning-or-worse template that never appeared before the end of the baseline;
               the change starts at its first line, if it appears MIN_NEW times within WIN_S
    warnings   the share of warning lines in a WIN_S window rose (logsig.py), in HOLD windows
               in a row; the change starts at the first of them
    latency    a method's median request time rose (logsig.py), in HOLD windows in a row

    drop       the line rate fell; reported as a NOTE, never as the onset (LOGS-PLAN.md 12.3)

Output: one row per change, earliest first, then one verdict line.

    LOG ONSET: <entity> (<kind>) first change at HH:MM:SS: <what>; also changed: <entity> HH:MM:SS, ...
    NO LOG CHANGE: ...    nothing changed in any entity after the baseline
    LOGS TOO SHORT: ...   the logs do not cover a baseline and a window after it
    NO LOGS: ...          the index holds no log lines

Read it as a witness, not a judge. The first entity to change is often a CALLER of the faulty
one (it logs the timeouts), and no change does not mean no fault: many faults print nothing.
Use the time as a hint for where to cut the kernel slices; the kernel check decides.

Self-test:  python -m pytest Blueprint/logkit/tests
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

try:
    from . import logidx as L
    from . import logsig as G
except ImportError:                      # run as a copied script
    import logidx as L
    import logsig as G

WARMUP_S = 5         # the first seconds of a run: containers settle, the load starts
BASE_S = 40          # baseline length. Injections in our runs start ~60 s after the first line
WIN_S = 10           # one comparison window
HOLD = 2             # a warning or latency change must hold this many windows in a row
TAIL_S = 15          # ignore the last seconds of the logs: the load stops there
TOP = 12             # rows printed (INQUEST: a few selected events, never volume)
MAX_NOTES = 4        # entities named in the line-rate note


@dataclass
class Change:
    t: float
    entity: str
    kind: str
    signal: str          # new | warnings | latency | drop
    what: str
    level: float
    generic: bool

    @property
    def score(self) -> float:
        """INQUEST's ranking: errors above warnings, generic timeout/retry lines halved."""
        s = {"new": self.level, "warnings": 2.5, "latency": 2.5, "drop": 1.0}[self.signal]
        return s * (0.5 if self.generic else 1.0)


def find_changes(idx: L.Index) -> tuple[list[Change], tuple[float, float]]:
    base = (idx.t0 + WARMUP_S, idx.t0 + WARMUP_S + BASE_S)
    end = idx.t1 - TAIL_S
    changes: list[Change] = []
    for e in idx.entities.values():
        if not e.lines:
            continue
        # new templates: their own first line is the onset
        for t in e.templates:
            if (t.level >= L.WARN and t.first >= base[1] and t.first < end
                    and t.count_in(t.first, t.first + WIN_S) >= G.MIN_NEW):
                changes.append(Change(t.first, e.name, e.kind, "new",
                                      "new template x%d: %s" % (t.count, G._quote(t.example)),
                                      t.level, t.generic))
        # windowed signals: the first window of a run of HOLD changed windows
        run_w = {"warnings": [], "latency": [], "drop": []}
        seen = set()
        w = base[1]
        while w + WIN_S <= end:
            d = G.diff(e, base, (w, w + WIN_S))
            hits = {"warnings": d.warn_rise, "latency": bool(d.latency), "drop": d.drop}
            for sig, hit in hits.items():
                streak = run_w[sig]
                if hit:
                    streak.append((w, d))
                    if len(streak) == HOLD and sig not in seen:
                        seen.add(sig)
                        w0, d0 = streak[0]
                        if sig == "warnings":
                            what = "known warnings %.1f/s -> %.1f/s" % (d0.base_warn_s, d0.win_warn_s)
                        elif sig == "latency":
                            c = max(d0.latency, key=lambda c: c.win_ms / c.base_ms)
                            what = "%s p50 %s -> %s ms" % (c.method, G._ms(c.base_ms), G._ms(c.win_ms))
                        else:
                            what = "lines %.0f/s -> %.0f/s" % (d0.base_lines_s, d0.win_lines_s)
                        changes.append(Change(w0, e.name, e.kind, sig, what, 2.0, False))
                else:
                    streak.clear()
            w += WIN_S
    changes.sort(key=lambda c: (c.t, -c.score))
    return changes, base


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="When did the application logs first change?")
    ap.add_argument("index", help="<run>.logidx.json.gz")
    ap.add_argument("--top", type=int, default=TOP, help="rows to print (default %d)" % TOP)
    a = ap.parse_args(argv)
    idx = L.load(a.index)

    if not idx.lines or idx.t0 is None:
        print("NO LOGS: the index of %s holds no log lines." % idx.run)
        return 0
    span = idx.t1 - idx.t0
    if span < WARMUP_S + BASE_S + HOLD * WIN_S + TAIL_S:
        print("LOGS TOO SHORT: the logs cover %.0f s; a baseline of %d s and a window after it "
              "need %d s." % (span, BASE_S, WARMUP_S + BASE_S + HOLD * WIN_S + TAIL_S))
        return 0

    changes, base = find_changes(idx)
    print("log index %s (profile %s): %d entities, %d lines, %s to %s" % (
        idx.run, idx.profile, len(idx.entities), idx.lines, L.hms(idx.t0), L.hms(idx.t1)))
    print("baseline %s to %s (the start of the run); windows of %d s after it" % (
        L.hms(base[0]), L.hms(base[1]), WIN_S))
    if not idx.clock_aligned:
        print("NOTE: these logs are not aligned with the trace clock; the times are the log's own.")
    print()

    # INQUEST's selection: the TOP highest-ranked changes, shown in time order
    shown = sorted(sorted(changes, key=lambda c: -c.score)[:a.top], key=lambda c: c.t)
    print("%-8s  %-16s %-9s %s" % ("time", "entity", "signal", "what"))
    for c in shown:
        print("%-8s  %-16s %-9s %s%s" % (L.hms(c.t), c.entity[:16], c.signal, c.what,
                                         "  (generic)" if c.generic else ""))
    if not shown:
        print("(none)")
    print()

    drops = [c for c in changes if c.signal == "drop"]
    if drops:
        names = ", ".join("%s at %s" % (c.entity, L.hms(c.t)) for c in drops[:MAX_NOTES])
        if len(drops) > MAX_NOTES:
            names += " and %d more" % (len(drops) - MAX_NOTES)
        print("NOTE: line rate fell in %s; a load phase ending looks the same, so this is not "
              "counted as a change." % names)
    real = [c for c in changes if c.signal != "drop"]
    if not real:
        print("NO LOG CHANGE: no new warning or error, no rise in warnings and no latency rise "
              "after %s in %d entities (%d lines). The logs show nothing; that does not mean "
              "the system is healthy." % (L.hms(base[1]), len(idx.entities), idx.lines))
        return 0
    first = real[0]
    others = []
    for c in real[1:]:
        if c.entity != first.entity and c.entity not in (o[0] for o in others):
            others.append((c.entity, L.hms(c.t)))
    print("LOG ONSET: %s (%s) first change at %s: %s%s" % (
        first.entity, first.kind, L.hms(first.t), first.what,
        "; also changed: " + ", ".join("%s %s" % o for o in others[:6]) if others else ""))
    print("NOTE: the first entity to change is often a caller of the faulty one; the kernel "
          "check decides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
