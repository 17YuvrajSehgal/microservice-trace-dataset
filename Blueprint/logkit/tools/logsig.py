#!/usr/bin/env python3
"""
logsig.py - what changed in one entity's logs between a baseline window and a later window.

Standard library only; copied next to the log tools. Both log_onset.py and log_window.py decide
"changed" through diff() here, so the two tools cannot disagree about what a change is.

Three signals count as a change (LOGS-PLAN.md section 2.4 saw all three):

    new        warning-or-worse templates that never appeared up to the end of the baseline,
               with at least MIN_NEW lines in the window TOGETHER. Rule history: per template,
               a crashing carts-db (15 different new error lines, 1 to 5 each) counted as
               nothing (disk_full_aggressive_steady_r2, 25-11-2026). The lines must also fall
               in at least MIN_SECONDS different seconds: edge-router wrote 7 "Error forwarding"
               lines in ONE second of a healthy run and never again (normal_none_burst_r1,
               25-11-2026); every real case went on for several seconds
    warnings   the SHARE of warning-or-worse lines among all lines rose SHARE_RATIO times. A share,
               not a rate: under a load burst a healthy service logs more of everything, and
               Sock Shop's front-end logs ~13 "payment declined" errors per second when healthy
    latency    a method's median request time rose LAT_RATIO times and by LAT_MIN_MS

One more is reported but does NOT count as a change, because the decision is open
(LOGS-PLAN.md section 12, item 3):

    drop       the entity's line rate fell RATE_RATIO times. It showed the culprit in
               code_event_loop_block (front-end 765 -> 41 lines/s), and it is also what the
               end of a load phase looks like

No error in the logs does not mean no fault. Nothing here reads silence as health.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from . import logidx as L
except ImportError:                      # run as a copied script, next to logidx.py
    import logidx as L

MIN_NEW = 3              # new warning/error lines needed in the window, all new templates together
MIN_SECONDS = 2          # ... spread over at least this many different seconds
SHARE_RATIO = 3.0        # warning share must rise this many times ...
MIN_WARN_RATE = 1.0      # ... and by at least this many warning lines per second
LAT_RATIO = 3.0          # median latency must rise this many times ...
LAT_MIN_MS = 5.0         # ... and by at least this many ms (catalogue's p50 is ~1 ms)
LAT_MIN_BASE = 20        # requests needed in the baseline for a latency comparison
LAT_MIN_WIN = 5          # requests needed in the window
RATE_RATIO = 3.0         # line rate must fall this many times ...
RATE_MIN = 5.0           # ... from at least this many lines per second


@dataclass
class LatencyChange:
    method: str
    base_ms: float
    win_ms: float
    base_n: int
    win_n: int


@dataclass
class Diff:
    entity: str
    kind: str
    base_lines_s: float
    win_lines_s: float
    base_warn_s: float
    win_warn_s: float
    new: list = field(default_factory=list)            # [L.Template]
    warn_rise: bool = False
    latency: list = field(default_factory=list)        # [LatencyChange], rises only
    drop: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.new or self.warn_rise or self.latency)

    def describe(self, max_new: int = 2) -> str:
        parts = []
        if self.new:
            n = len(self.new)
            parts.append("%d new warning/error template%s (first at %s: %s)" % (
                n, "" if n == 1 else "s", L.hms(min(t.first for t in self.new)),
                _quote(min(self.new, key=lambda t: t.first).example)))
        if self.warn_rise:
            parts.append("known warnings %.1f/s -> %.1f/s (share of lines %.0f%% -> %.0f%%)" % (
                self.base_warn_s, self.win_warn_s,
                100 * _share(self.base_warn_s, self.base_lines_s),
                100 * _share(self.win_warn_s, self.win_lines_s)))
        for c in sorted(self.latency, key=lambda c: -c.win_ms / c.base_ms)[:3]:
            parts.append("%s p50 %s -> %s ms" % (c.method, _ms(c.base_ms), _ms(c.win_ms)))
        if self.drop:
            parts.append("lines %.0f/s -> %.0f/s" % (self.base_lines_s, self.win_lines_s))
        return "; ".join(parts) or "no change"


def _share(warn: float, lines: float) -> float:
    return warn / lines if lines else 0.0


def _ms(x: float) -> str:
    return "%.0f" % x if x >= 10 else "%.1f" % x


def _quote(text: str, n: int = 100) -> str:
    text = " ".join(text.split())
    return '"%s"' % (text if len(text) <= n else text[:n - 3] + "...")


def is_burst(templates: list, a: float, b: float) -> bool:
    """Enough new warning lines in [a, b), over enough different seconds, to count as a change."""
    lines = sum(t.count_in(a, b) for t in templates)
    seconds = {s for t in templates for s in t.series if L.in_window(s, a, b)}
    return lines >= MIN_NEW and len(seconds) >= MIN_SECONDS


def diff(e: L.Entity, base: tuple, win: tuple) -> Diff:
    """Compare window `win` = (a, b) with window `base` = (a, b), epoch seconds."""
    (ba, bb), (wa, wb) = base, win
    bsec, wsec = max(1.0, bb - ba), max(1.0, wb - wa)
    new = [t for t in e.templates if t.level >= L.WARN and t.first >= bb and t.count_in(wa, wb)]
    if not is_burst(new, wa, wb):
        new = []
    new_keys = {t.key for t in new}
    old_keys = {t.key for t in e.templates if t.key not in new_keys}
    base_lines, win_lines = e.lines_in(ba, bb) / bsec, e.lines_in(wa, wb) / wsec
    base_warn = e.warnings_in(ba, bb, old_keys) / bsec
    win_warn_old = e.warnings_in(wa, wb, old_keys) / wsec
    # warnings of templates already seen before the window; the new ones are counted in `new`
    d = Diff(entity=e.name, kind=e.kind, base_lines_s=base_lines, win_lines_s=win_lines,
             base_warn_s=base_warn, win_warn_s=win_warn_old, new=new)
    bshare, wshare = _share(base_warn, base_lines), _share(win_warn_old, win_lines)
    d.warn_rise = (win_warn_old - base_warn >= MIN_WARN_RATE
                   and (bshare == 0 or wshare >= SHARE_RATIO * bshare))
    for method in e.latency:
        bh, wh = e.latency_hist(method, ba, bb), e.latency_hist(method, wa, wb)
        bn, wn = sum(bh.values()), sum(wh.values())
        if bn < LAT_MIN_BASE or wn < LAT_MIN_WIN:
            continue
        b50, w50 = L.quantile(bh, 0.5), L.quantile(wh, 0.5)
        if w50 >= LAT_RATIO * b50 and w50 - b50 >= LAT_MIN_MS:
            d.latency.append(LatencyChange(method, b50, w50, bn, wn))
    d.drop = base_lines >= RATE_MIN and win_lines * RATE_RATIO <= base_lines
    return d
