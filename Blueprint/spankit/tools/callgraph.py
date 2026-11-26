#!/usr/bin/env python3
"""
callgraph.py - who calls whom in this run, read from its request traces (OTLP spans).

Usage:
    python3 callgraph.py <run.callgraph.json>                      the whole graph
    python3 callgraph.py <run.callgraph.json> --around front-end   one service's callers and callees

Input: a graph built by `python -m spankit.build`. Standard library only, so it can be copied into
a blueprint's tools/ folder and run with a bare `python3`. It is also the one place the graph
format is defined: the builder imports SCHEMA_VERSION from here.

Why it exists: a service whose logs show errors is usually a CALLER of the faulty one (it logs
the timeouts of what it waits on). Its callees are where to look next.

Read the gaps it prints. A service that writes no spans (a database, a proxy, an uninstrumented
service) can appear as a callee, but its own calls are unknown. A service with spans but no
outgoing span has callees that are unknown, not absent.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import dataclass

SCHEMA_VERSION = 2          # 2: edges carry `via` and `db` (26-11-2026)


@dataclass
class Graph:
    run: str
    has_spans: bool
    edges: dict[tuple[str, str], int]
    dbs: dict[tuple[str, str], list[str]]
    services: dict[str, dict]
    silent: set[str]
    no_outgoing: set[str]

    def callees(self, svc: str) -> dict[str, int]:
        return {b: n for (a, b), n in self.edges.items() if a == svc}

    def databases(self, svc: str) -> set[str]:
        """Database products named on svc's outgoing calls (db.system), also behind a proxy."""
        return {d for (a, _b), ds in self.dbs.items() if a == svc for d in ds}

    def callers(self, svc: str) -> dict[str, int]:
        return {a: n for (a, b), n in self.edges.items() if b == svc}

    def known_callees(self, svc: str) -> bool:
        """False when the graph cannot say what `svc` calls (no spans, or no outgoing spans)."""
        return self.has_spans and svc in self.services and svc not in self.no_outgoing


def load(path: str) -> Graph:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"{path}: call graph schema {d.get('schema')}, this reader knows "
                         f"{SCHEMA_VERSION}; rebuild the graph")
    return Graph(run=d.get("run", "?"), has_spans=d.get("source") is not None,
                 edges={(e["caller"], e["callee"]): int(e["calls"]) for e in d["edges"]},
                 dbs={(e["caller"], e["callee"]): list(e.get("db", ())) for e in d["edges"]},
                 services=d.get("services", {}), silent=set(d.get("silent_callees", ())),
                 no_outgoing=set(d.get("no_outgoing", ())))


def _line(g: Graph, svc: str) -> str:
    def one(c, n):
        db = g.dbs.get((svc, c))
        return "%s (%d%s)" % (c, n, "; db " + "/".join(db) if db else "")

    out = ", ".join(one(c, n) for c, n in sorted(g.callees(svc).items(), key=lambda kv: -kv[1]))
    if out:
        return out
    if svc in g.silent:
        return "unknown (writes no spans)"
    return "unknown (no outgoing spans)" if not g.known_callees(svc) else "none seen"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Who calls whom, from the run's request traces.")
    ap.add_argument("graph", help="<run>.callgraph.json")
    ap.add_argument("--around", help="one service: its callers and callees")
    a = ap.parse_args(argv)
    g = load(a.graph)
    if not g.has_spans:
        print("NO SPANS: %s has no request traces, so the call graph is unknown." % g.run)
        return 0
    if a.around:
        svc = a.around
        callers = g.callers(svc)
        print("CALLEES of %s: %s" % (svc, _line(g, svc)))
        print("CALLERS of %s: %s" % (svc, ", ".join("%s (%d)" % kv for kv in sorted(
            callers.items(), key=lambda kv: -kv[1])) or "none seen"))
        if svc in g.silent:
            print("NOTE: %s writes no spans; it is seen only as a callee." % svc)
        return 0
    print("call graph of %s: %d services with spans, %d edges (calls counted)" % (
        g.run, len(g.services), len(g.edges)))
    for svc in sorted(set(g.services) | g.silent):
        print("  %-28s -> %s" % (svc, _line(g, svc)))
    if g.silent:
        print("NOTE: no spans at all, seen only as callees: %s" % ", ".join(sorted(g.silent)))
    if g.no_outgoing:
        print("NOTE: spans but no outgoing span, so their callees are unknown: %s"
              % ", ".join(sorted(g.no_outgoing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
