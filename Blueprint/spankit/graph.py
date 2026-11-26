"""The service call graph of one run, from its spans.

An edge caller -> callee comes from an outgoing span of the caller (CLIENT or PRODUCER), named in
this order:

  1. span link: the callee's own incoming span (SERVER or CONSUMER) has the caller's span as its
     parent. Exact, and needs no names: Train Ticket's services find each other through a
     registry and call each other by IP address, so an attribute often names only an IP.
  2. attribute: the outgoing span names its peer (server.address, else peer.service,
     net.peer.name, messaging.system). This is the only way to see a callee that writes no spans:
     a database, a message broker, a proxy.
  3. address: the peer is named only by an IP. It is resolved through the links and attributes of
     other spans to that IP; if none names it, the edge is kept as `ip:<address>` and listed.

Each edge also records the database products its spans name (db.system), because a proxy can
stand between a service and its database: Train Ticket's services call `toxiproxy`, whose spans
say mysql.

A CONSUMER span that reads from a broker (queue-master from rabbitmq) is also a call of its own:
it counts as an edge to the broker it names.

What spans cannot show is reported, not guessed:
  - silent services: a service that writes no spans at all (Sock Shop's edge-router, user,
    payment) can still be a callee, but its own calls are invisible;
  - callers with no outgoing spans: a traced service whose client calls are not traced (Sock
    Shop's catalogue, whose database calls write no span), so its callees are unknown.
"""
from __future__ import annotations

import gzip
import ipaddress
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from spankit.otlp import (
    ADDRESS_KEYS,
    CONSUMER,
    DB_KEY,
    INCOMING,
    OUTGOING,
    PEER_KEYS,
    SERVER,
    ReadStats,
    read_spans,
    spans_path,
)
from spankit.tools.callgraph import SCHEMA_VERSION


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _peer_name(peer: dict[str, str]) -> str | None:
    for key in PEER_KEYS:
        v = peer.get(key)
        if v:
            return None if _is_ip(v) else v.split(":")[0]
    return None


def _peer_address(peer: dict[str, str]) -> str | None:
    for key in ADDRESS_KEYS + ("server.address",):
        v = peer.get(key)
        if v and _is_ip(v):
            return v
    return None


def build_graph(run_dir: str | os.PathLike) -> dict:
    """The call graph of one run as a JSON-ready dict."""
    path = spans_path(run_dir)
    stats = ReadStats()
    spans, servers, outgoing = Counter(), Counter(), Counter()
    calls = []                                   # (caller, span_id, peer) of every outgoing span
    child_of: dict[str, str] = {}                # parent span id -> service of the incoming span
    consumed = Counter()                         # (consumer, broker) for CONSUMER spans
    if path.is_file():
        for s in read_spans(path, stats):
            spans[s.service] += 1
            if s.kind == SERVER:
                servers[s.service] += 1
            if s.kind in INCOMING and s.parent_id:
                child_of[s.parent_id] = s.service
            if s.kind in OUTGOING:
                outgoing[s.service] += 1
                calls.append((s.service, s.span_id, s.peer))
            elif s.kind == CONSUMER:
                broker = _peer_name(s.peer)
                if broker and broker != s.service:
                    outgoing[s.service] += 1
                    consumed[(s.service, broker)] += 1

    # IP -> service, learned from calls whose callee is known by link or by name
    ip_names: dict[str, Counter] = defaultdict(Counter)
    for _caller, span_id, peer in calls:
        addr = _peer_address(peer)
        name = child_of.get(span_id) or _peer_name(peer)
        if addr and name:
            ip_names[addr][name] += 1

    edges = Counter()
    via = defaultdict(Counter)
    dbs = defaultdict(set)
    unresolved = set()
    for caller, span_id, peer in calls:
        callee, how = child_of.get(span_id), "span_link"
        if not callee:
            callee, how = _peer_name(peer), "attribute"
        if not callee:
            addr = _peer_address(peer)
            if not addr:
                continue
            names = ip_names.get(addr)
            if names:
                callee, how = names.most_common(1)[0][0], "address"
            else:
                callee, how = "ip:" + addr, "address"
                unresolved.add(addr)
        if callee == caller:
            continue
        edges[(caller, callee)] += 1
        via[(caller, callee)][how] += 1
        if peer.get(DB_KEY):
            dbs[(caller, callee)].add(peer[DB_KEY])
    for key, n in consumed.items():
        edges[key] += n
        via[key]["attribute"] += n

    callees = {c for _, c in edges}
    return {
        "schema": SCHEMA_VERSION, "run": Path(run_dir).name,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(path.relative_to(run_dir)) if path.is_file() else None,
        "read": {"lines": stats.lines, "bad_lines": stats.bad_lines, "spans": stats.spans},
        "services": {name: {"spans": n, "server": servers[name], "outgoing": outgoing[name]}
                     for name, n in sorted(spans.items())},
        "edges": [{"caller": a, "callee": b, "calls": n, "via": dict(via[(a, b)]),
                   "db": sorted(dbs[(a, b)])} for (a, b), n in sorted(edges.items())],
        "silent_callees": sorted(c for c in callees if c not in spans and not c.startswith("ip:")),
        "no_outgoing": sorted(s for s in spans if not outgoing[s]),
        "unresolved_ips": sorted(unresolved),
    }


def write_graph(graph: dict, out: str | os.PathLike) -> None:
    """Write atomically: a half-written graph must never be read as a whole one."""
    out = Path(out)
    tmp = out.with_name(out.name + ".partial")
    opener = gzip.open if out.suffix == ".gz" else open
    with opener(tmp, "wt", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=1)
    os.replace(tmp, out)
