"""Build a log index: read a run's logs once, keep what the tools need.

Per entity: lines per second, templates (level, first and last time, count, counts per second,
one example line), and request latency per method per second as a histogram. The format is
defined by logkit/tools/logidx.py, which also reads it.

Cost measured with the first version (logtool.py, 16-11-2026): 250 MB of Sock Shop logs in
7.5 s on a laptop.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from logkit import templating as T
from logkit.profile import SourceProfile
from logkit.tools.logidx import SCHEMA_VERSION, bin_of

MAX_TEMPLATES = 4000          # per entity; later new templates fold into one row
OTHER = "<other templates>"
EXAMPLE_CHARS = 400
DURATION = re.compile(r"(\d+(?:\.\d+)?)(ns|µs|us|ms|s|m|h)")
DURATION_MS = {"ns": 1e-6, "µs": 1e-3, "us": 1e-3, "ms": 1.0, "s": 1e3, "m": 6e4, "h": 3.6e6}


def duration_ms(text: str) -> float | None:
    """A Go duration (1.27ms, 980.3µs, 694ns, 1m2.5s) in milliseconds."""
    parts = DURATION.findall(text)
    return sum(float(n) * DURATION_MS[u] for n, u in parts) if parts else None


@dataclass
class _Tpl:
    level: float
    generic: bool
    example: str
    first: float | None = None
    last: float | None = None
    count: int = 0
    series: Counter = field(default_factory=Counter)


@dataclass
class _Ent:
    kind: str
    lines: int = 0
    frames: int = 0
    t0: float | None = None
    t1: float | None = None
    rate: Counter = field(default_factory=Counter)
    tpls: dict[str, _Tpl] = field(default_factory=dict)
    latency: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(Counter)))


def build_index(run_dir: str | os.PathLike, profile: SourceProfile) -> dict:
    """The index of one run as a JSON-ready dict."""
    ents: dict[str, _Ent] = {}
    skipped: dict[str, int] = {}
    if profile.entity_from == "filename":
        # an empty file is still an entity: "orders-db wrote nothing" is worth knowing
        for path in profile.paths(run_dir):
            ents.setdefault(profile.entity_of(path, None), _Ent(kind=profile.kind))
    for rec in profile.records(run_dir, skipped):
        e = ents.get(rec.entity)
        if e is None:
            e = ents[rec.entity] = _Ent(kind=rec.kind)
        if not rec.msg.strip():
            continue
        if T.is_frame(rec.msg):
            e.frames += 1
            continue
        e.lines += 1
        t = rec.t
        sec = None if t is None else int(t)
        if t is not None:
            e.t0 = t if e.t0 is None else min(e.t0, t)
            e.t1 = t if e.t1 is None else max(e.t1, t)
            e.rate[sec] += 1
        key = T.template(rec.msg)
        tp = e.tpls.get(key)
        if tp is None:
            if len(e.tpls) >= MAX_TEMPLATES:
                key = OTHER          # ponytail: one overflow row; raise MAX_TEMPLATES if it fills
                tp = e.tpls.get(key)
            if tp is None:
                tp = e.tpls[key] = _Tpl(level=T.level(rec.msg), generic=T.is_generic(rec.msg),
                                        example=rec.msg[:EXAMPLE_CHARS])
        tp.count += 1
        if t is not None:
            tp.first = t if tp.first is None else min(tp.first, t)
            tp.last = t if tp.last is None else max(tp.last, t)
            tp.series[sec] += 1
            if profile.latency is not None:
                m = profile.latency.regex.search(rec.msg)
                ms = duration_ms(m.group(1)) if m else None
                if ms is not None:
                    mm = profile.latency.method.search(rec.msg) if profile.latency.method else None
                    e.latency[mm.group(1) if mm else "?"][sec][bin_of(ms)] += 1
    for name in skipped:
        ents.setdefault(name, _Ent(kind=profile.kind))

    starts = [e.t0 for e in ents.values() if e.t0 is not None]
    t0 = math.floor(min(starts)) if starts else None
    t1 = max((e.t1 for e in ents.values() if e.t1 is not None), default=None)

    def rel(x):
        return None if x is None or t0 is None else round(x - t0, 3)

    def ser(c):
        return {str(s - t0): n for s, n in sorted(c.items())}

    out_ents = {}
    for name, e in sorted(ents.items()):
        out_ents[name] = {
            "kind": e.kind, "lines": e.lines, "skipped": skipped.get(name, 0), "frames": e.frames,
            "t0": rel(e.t0), "t1": rel(e.t1), "rate": ser(e.rate),
            "templates": [{"key": k, "level": tp.level, "generic": tp.generic,
                           "first": rel(tp.first), "last": rel(tp.last), "count": tp.count,
                           "example": tp.example, "series": ser(tp.series)}
                          for k, tp in e.tpls.items() if tp.first is not None],
            "latency": {m: {str(s - t0): {str(b): n for b, n in sorted(h.items())}
                            for s, h in sorted(by_s.items())}
                        for m, by_s in e.latency.items()},
        }
    return {"schema": SCHEMA_VERSION, "profile": profile.id, "run": Path(run_dir).name,
            "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "clock": {"aligned": profile.clock_offset_s is not None,
                      "offset_s": profile.clock_offset_s},
            "t0": t0, "t1": t1, "entities": out_ents}


def write_index(index: dict, out: str | os.PathLike) -> None:
    """Write atomically: a half-written index must never be read as a whole one."""
    out = Path(out)
    tmp = out.with_name(out.name + ".partial")
    opener = gzip.open if out.suffix == ".gz" else open
    with opener(tmp, "wt", encoding="utf-8") as fh:
        json.dump(index, fh, separators=(",", ":"))
    os.replace(tmp, out)
