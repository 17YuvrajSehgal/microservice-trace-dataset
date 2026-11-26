"""Source profiles: how one log FORMAT is read.

A profile is a YAML file in `logkit/profiles/`. Adding a log source means adding a file there;
no tool and no blueprint changes. Fields:

    id          the profile's name (the file name without .yaml)
    files       glob(s), relative to the run directory, of the files to read (.gz is fine)
    line        regex with the named groups `ts` and `msg`; a line that does not match is a
                continuation and keeps the previous line's time
    ts_format   iso_utc (2026-09-05T15:18:46.94Z) | epoch (seconds, may have a fraction)
    entity      {from: filename, strip: [regex, ...]}  or  {from: group, group: <name>}
    kind        container | process | thread | host
    skip        substrings; a line holding one is counted and dropped (span relays and the like)
    latency     optional {regex: <group 1 = a Go duration>, method: <regex, group 1>}
    clock       {offset_s: <seconds to add to reach the trace clock>}  or  {status: unknown}

The safety rule of the repo holds here too: nothing an agent reaches may read ground truth.
A profile whose `files` could reach a run's ground_truth.json, verification files or manifest
is refused when it is loaded, and every matched path is checked again before it is opened.
"""
from __future__ import annotations

import calendar
import glob
import gzip
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

from logkit.record import LogRecord

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
KINDS = frozenset({"container", "process", "thread", "host"})
TS_FORMATS = frozenset({"iso_utc", "epoch"})
# Files that hold the answer, never readable through a profile (see ctf_tool.py, codetool.py).
# Matched at the START of a file or folder name: Train Ticket has a service called
# ts-verification-code-service, and a plain search refused every one of its 134 runs (26-11-2026).
FORBIDDEN = re.compile(r"(?:^|[\\/])(?:ground_?truth|verification|MANIFEST|SHA256SUMS|fault[_-]?state)",
                       re.I)


class ProfileError(ValueError):
    """A profile file is missing a field or asks for something it may not."""


@dataclass(frozen=True)
class Latency:
    regex: re.Pattern
    method: re.Pattern | None


@dataclass(frozen=True)
class SourceProfile:
    id: str
    files: tuple[str, ...]
    line: re.Pattern
    ts_format: str
    entity_from: str
    entity_strip: tuple[re.Pattern, ...]
    entity_group: str | None
    kind: str
    skip: tuple[str, ...]
    latency: Latency | None
    clock_offset_s: float | None          # None = the log clock is not aligned with the trace

    # -- construction -------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict) -> SourceProfile:
        def need(key):
            if key not in d:
                raise ProfileError(f"profile {d.get('id', '?')!r}: missing field {key!r}")
            return d[key]

        pid = need("id")
        files = need("files")
        files = (files,) if isinstance(files, str) else tuple(files)
        for pattern in files:
            if (".." in Path(pattern).parts or os.path.isabs(pattern) or pattern.startswith(("/", "\\"))
                    or FORBIDDEN.search(pattern)):
                raise ProfileError(f"profile {pid!r}: files pattern {pattern!r} is not allowed")
        line = re.compile(need("line"))
        if not {"ts", "msg"} <= set(line.groupindex):
            raise ProfileError(f"profile {pid!r}: `line` needs the named groups ts and msg")
        ts_format = need("ts_format")
        if ts_format not in TS_FORMATS:
            raise ProfileError(f"profile {pid!r}: ts_format must be one of {sorted(TS_FORMATS)}")
        ent = need("entity")
        if ent.get("from") not in ("filename", "group"):
            raise ProfileError(f"profile {pid!r}: entity.from must be filename or group")
        if ent["from"] == "group" and ent.get("group") not in line.groupindex:
            raise ProfileError(f"profile {pid!r}: entity.group must name a group of `line`")
        kind = need("kind")
        if kind not in KINDS:
            raise ProfileError(f"profile {pid!r}: kind must be one of {sorted(KINDS)}")
        lat = d.get("latency")
        latency = None
        if lat:
            latency = Latency(re.compile(lat["regex"]),
                              re.compile(lat["method"]) if lat.get("method") else None)
        clock = d.get("clock") or {}
        offset = None if clock.get("status") == "unknown" else float(clock.get("offset_s", 0.0))
        return cls(id=pid, files=files, line=line, ts_format=ts_format,
                   entity_from=ent["from"],
                   entity_strip=tuple(re.compile(p) for p in ent.get("strip", ())),
                   entity_group=ent.get("group"), kind=kind,
                   skip=tuple(d.get("skip", ())), latency=latency, clock_offset_s=offset)

    # -- reading ------------------------------------------------------------------------
    def paths(self, run_dir: str | os.PathLike) -> list[Path]:
        """The files this profile reads in one run, sorted. Checked against the safety rule."""
        root = Path(run_dir).resolve()
        out = []
        for pattern in self.files:
            for p in glob.glob(str(root / pattern)):
                path = Path(p).resolve()
                if root not in path.parents or FORBIDDEN.search(path.name):
                    raise ProfileError(f"refusing to read {path}: outside the run or forbidden")
                if path.is_file():
                    out.append(path)
        return sorted(set(out))

    def entity_of(self, path: Path, match: re.Match | None) -> str:
        if self.entity_from == "group":
            return (match.group(self.entity_group) if match else "") or "?"
        name = path.name
        for rx in self.entity_strip:
            name = rx.sub("", name)
        return name or "?"

    def parse_ts(self, text: str) -> float:
        if self.ts_format == "epoch":
            return float(text)
        return _iso_utc(text)

    def records(self, run_dir: str | os.PathLike, skipped: dict[str, int] | None = None
                ) -> Iterator[LogRecord]:
        """Every kept line of every file, in file order. Skipped lines are counted per entity
        in `skipped`, if given."""
        root = Path(run_dir).resolve()
        offset = self.clock_offset_s or 0.0
        for path in self.paths(root):
            src = path.relative_to(root).as_posix()
            fixed_entity = None if self.entity_from == "group" else self.entity_of(path, None)
            last_t = None
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.rstrip("\n")
                    m = self.line.match(raw)
                    if m:
                        try:
                            last_t = self.parse_ts(m.group("ts")) + offset
                        except ValueError:
                            pass
                        msg = m.group("msg")
                    else:
                        msg = raw
                    entity = fixed_entity or self.entity_of(path, m)
                    if any(s in msg for s in self.skip):
                        if skipped is not None:
                            skipped[entity] = skipped.get(entity, 0) + 1
                        continue
                    yield LogRecord(t=last_t, entity=entity, kind=self.kind, msg=msg, src=src)


_DAY_CACHE: dict[str, int] = {}
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?Z?$")


def _iso_utc(text: str) -> float:
    """'2026-09-05T15:18:46.942215124Z' -> epoch seconds. Nanosecond fractions are kept, which
    datetime.fromisoformat would refuse; the day's epoch is cached (one parse per line)."""
    m = _ISO.match(text)
    if not m:
        raise ValueError(f"not an ISO UTC time: {text!r}")
    y, mo, d, h, mi, s, frac = m.groups()
    day = f"{y}-{mo}-{d}"
    base = _DAY_CACHE.get(day)
    if base is None:
        base = _DAY_CACHE[day] = calendar.timegm((int(y), int(mo), int(d), 0, 0, 0))
    return base + int(h) * 3600 + int(mi) * 60 + int(s) + (float(frac) if frac else 0.0)


def load_profile(name_or_path: str | os.PathLike) -> SourceProfile:
    """A profile by id (a file in logkit/profiles/) or by path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = PROFILE_DIR / f"{name_or_path}.yaml"
    if not path.is_file():
        known = sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))
        raise ProfileError(f"no profile {name_or_path!r}; known: {known}")
    with open(path, encoding="utf-8") as fh:
        return SourceProfile.from_dict(yaml.safe_load(fh))
