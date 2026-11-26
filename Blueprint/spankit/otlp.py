"""Stream an OTLP JSON-lines span file (the collector's file exporter) into Span records.

Each line is one export batch: {"resourceSpans": [{"resource": {...}, "scopeSpans": [{"spans":
[...]}]}]}. A run's file is a byte-offset slice of the campaign's file (collect_trace.sh), so its
first and last line can be cut in the middle: a line that does not parse is counted and skipped.

Only what the call graph needs is kept: the service, the span kind, the ids that link a call to
its callee, and the attributes that name a peer. A run holds over a million spans, so nothing
else is copied.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

SPANS = Path("otlp") / "spans.jsonl"
# OTLP span kinds (the JSON exporter writes the enum's number)
INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER = 1, 2, 3, 4, 5
OUTGOING = (CLIENT, PRODUCER)          # a call this service makes
INCOMING = (SERVER, CONSUMER)          # a call this service receives
KIND_NAMES = {"SPAN_KIND_INTERNAL": 1, "SPAN_KIND_SERVER": 2, "SPAN_KIND_CLIENT": 3,
              "SPAN_KIND_PRODUCER": 4, "SPAN_KIND_CONSUMER": 5}
# attributes that name the other side of a call, newest semantic conventions first
PEER_KEYS = ("server.address", "peer.service", "net.peer.name", "messaging.system")
ADDRESS_KEYS = ("network.peer.address", "net.peer.ip", "net.sock.peer.addr")
DB_KEY = "db.system"


@dataclass(slots=True)
class Span:
    service: str
    kind: int
    span_id: str = ""            # kept for outgoing spans: a callee's span names it as parent
    parent_id: str = ""          # kept for incoming spans
    peer: dict[str, str] = field(default_factory=dict)


@dataclass
class ReadStats:
    lines: int = 0
    bad_lines: int = 0
    spans: int = 0


def _value(v: dict) -> str | None:
    for k in ("stringValue", "intValue"):
        if k in v:
            return str(v[k])
    return None


def _kind(k) -> int:
    if isinstance(k, int):
        return k
    return KIND_NAMES.get(str(k), 0)


def spans_path(run_dir: str | os.PathLike) -> Path:
    return Path(run_dir) / SPANS


def read_spans(path: str | os.PathLike, stats: ReadStats | None = None) -> Iterator[Span]:
    """Every span of the file, with ids and peer attributes only where the graph uses them."""
    stats = stats if stats is not None else ReadStats()
    wanted = set(PEER_KEYS) | set(ADDRESS_KEYS) | {DB_KEY}
    with open(path, "rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            stats.lines += 1
            try:
                batch = json.loads(line)
            except ValueError:
                stats.bad_lines += 1
                continue
            for rs in batch.get("resourceSpans", ()):
                service = "?"
                for a in rs.get("resource", {}).get("attributes", ()):
                    if a.get("key") == "service.name":
                        service = _value(a.get("value", {})) or "?"
                        break
                for ss in rs.get("scopeSpans", ()):
                    for s in ss.get("spans", ()):
                        stats.spans += 1
                        kind = _kind(s.get("kind"))
                        if kind in OUTGOING or kind == CONSUMER:
                            peer = {}
                            for a in s.get("attributes", ()):
                                if a.get("key") in wanted:
                                    v = _value(a.get("value", {}))
                                    if v:
                                        peer[a["key"]] = v
                            yield Span(service, kind, s.get("spanId", ""), s.get("parentSpanId", ""), peer)
                        elif kind == SERVER:
                            yield Span(service, kind, parent_id=s.get("parentSpanId", ""))
                        else:
                            yield Span(service, kind)
