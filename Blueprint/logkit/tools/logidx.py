#!/usr/bin/env python3
"""
logidx.py - read a log index (<run>.logidx.json.gz) for the log tools.

Standard library only. It is copied next to log_onset.py and log_window.py in a blueprint's
tools/ folder. It is also the one place that defines the index format: the builder
(logkit/index.py) imports SCHEMA_VERSION and the latency bins from here, so writer and reader
cannot drift apart.

The index, per entity (a container, a process): lines per second, message templates with their
counts per second, and request latency per method per second as a histogram. Times inside the
file are whole seconds from the index's t0; this module turns them back into epoch seconds.

Latency is kept as a histogram with BINS_PER_DECADE bins per factor of 10 (about 12% wide), so
a p50 over any window is exact to within one bin. Raw samples would be 30,000 floats per method.
"""
from __future__ import annotations

import calendar
import gzip
import json
import math
import re
import time
from dataclasses import dataclass, field

SCHEMA_VERSION = 1
BINS_PER_DECADE = 20
MIN_MS = 1e-3                     # 1 microsecond; anything faster lands in the lowest bin
WARN = 2.0                        # level: 2 warning, 3 error, 4 fatal (logkit.templating)


# -- latency bins ---------------------------------------------------------------------------
def bin_of(ms: float) -> int:
    return math.floor(BINS_PER_DECADE * math.log10(max(ms, MIN_MS)))


def value_of(b: int) -> float:
    """The middle of a bin, in ms (geometric middle)."""
    return 10 ** ((b + 0.5) / BINS_PER_DECADE)


def quantile(hist: dict[int, int], q: float) -> float | None:
    n = sum(hist.values())
    if not n:
        return None
    rank, seen = q * (n - 1), 0
    for b in sorted(hist):
        seen += hist[b]
        if seen > rank:
            return value_of(b)
    return value_of(max(hist))


# -- time -----------------------------------------------------------------------------------
_HMS = re.compile(r"^(?:(\d{4}-\d\d-\d\d)[ T])?(\d{1,2}):(\d\d):(\d\d(?:\.\d+)?)$")


def hms(epoch: float | None) -> str:
    if epoch is None:
        return "-"
    return time.strftime("%H:%M:%S", time.gmtime(epoch))


def resolve_time(text: str, ref: float) -> float:
    """'HH:MM:SS' (or 'YYYY-MM-DD HH:MM:SS') -> epoch seconds, on the day of `ref`. A clock time
    more than 12 h before `ref` is taken as the next day (a recording across midnight)."""
    m = _HMS.match(text.strip())
    if not m:
        raise ValueError(f"cannot read the time {text!r}; use HH:MM:SS")
    day, h, mi, s = m.groups()
    secs = int(h) * 3600 + int(mi) * 60 + float(s)
    if day:
        y, mo, d = (int(x) for x in day.split("-"))
        return calendar.timegm((y, mo, d, 0, 0, 0)) + secs
    midnight = ref - (ref % 86400)
    t = midnight + secs
    if t < ref - 43200:
        t += 86400
    return t


def window_sum(series: dict[int, int], a: float, b: float) -> int:
    """Sum of the counts of the whole seconds s with floor(a) <= s < b.

    Counts are kept per whole second, so a window that starts at a line's own time (22:54:07.448)
    must include the second 22:54:07. Rule history: `a <= s` dropped it, and every new template
    counted 0 lines in its first window (disk_full_aggressive_steady_r2, 25-11-2026)."""
    return sum(n for s, n in series.items() if in_window(s, a, b))


def in_window(second: int, a: float, b: float) -> bool:
    """Whether the whole second `second` counts for the window [a, b) (see window_sum)."""
    return math.floor(a) <= second < b


# -- the index ------------------------------------------------------------------------------
@dataclass
class Template:
    key: str
    level: float
    generic: bool
    first: float
    last: float
    count: int
    example: str
    series: dict[int, int]

    def count_in(self, a: float, b: float) -> int:
        return window_sum(self.series, a, b)


@dataclass
class Entity:
    name: str
    kind: str
    lines: int
    skipped: int
    frames: int
    t0: float | None
    t1: float | None
    rate: dict[int, int]
    templates: list[Template]
    latency: dict[str, dict[int, dict[int, int]]] = field(default_factory=dict)

    def lines_in(self, a: float, b: float) -> int:
        return window_sum(self.rate, a, b)

    def warnings_in(self, a: float, b: float, keys: set[str] | None = None) -> int:
        """Lines of warning level or worse in [a, b); only these templates when keys is given."""
        return sum(t.count_in(a, b) for t in self.templates
                   if t.level >= WARN and (keys is None or t.key in keys))

    def latency_hist(self, method: str, a: float, b: float) -> dict[int, int]:
        out: dict[int, int] = {}
        for s, hist in self.latency.get(method, {}).items():
            if a <= s < b:
                for k, n in hist.items():
                    out[k] = out.get(k, 0) + n
        return out


@dataclass
class Index:
    run: str
    profile: str
    clock_aligned: bool
    t0: float | None
    t1: float | None
    entities: dict[str, Entity]

    @property
    def lines(self) -> int:
        return sum(e.lines for e in self.entities.values())


def load(path: str) -> Index:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"{path}: log index schema {d.get('schema')}, this reader knows "
                         f"{SCHEMA_VERSION}; rebuild the index")
    base = d.get("t0") or 0

    def series(m):
        return {base + int(k): int(v) for k, v in m.items()}

    ents = {}
    for name, e in d["entities"].items():
        tpls = [Template(key=t["key"], level=float(t["level"]), generic=bool(t["generic"]),
                         first=base + t["first"], last=base + t["last"], count=int(t["count"]),
                         example=t["example"], series=series(t["series"]))
                for t in e["templates"]]
        lat = {m: {base + int(s): {int(k): int(n) for k, n in h.items()} for s, h in by_s.items()}
               for m, by_s in e.get("latency", {}).items()}
        ents[name] = Entity(name=name, kind=e["kind"], lines=e["lines"], skipped=e["skipped"],
                            frames=e.get("frames", 0),
                            t0=None if e["t0"] is None else base + e["t0"],
                            t1=None if e["t1"] is None else base + e["t1"],
                            rate=series(e["rate"]), templates=tpls, latency=lat)
    return Index(run=d.get("run", "?"), profile=d.get("profile", "?"),
                 clock_aligned=bool(d.get("clock", {}).get("aligned")),
                 t0=d.get("t0"), t1=d.get("t1"), entities=ents)
