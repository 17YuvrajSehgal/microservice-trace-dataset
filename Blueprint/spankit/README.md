# spankit

A run's request traces (OTLP spans) read once into a service call graph. It is used to narrow
where to look ([`../latency/LOGS-PLAN.md`](../latency/LOGS-PLAN.md) section 6.5): the service
whose logs change is usually the CALLER of the faulty one, so the next places to look are the
services it calls.

## Layout

```
spankit/
  otlp.py            streams otlp/spans.jsonl into Span records; cut lines counted and skipped
  graph.py           Span records -> the call graph of one run, with its blind spots
  build.py           CLI: python -m spankit.build
  tools/
    callgraph.py     the graph format and its reader, and a CLI. STANDARD LIBRARY ONLY
  tests/             pytest, on a synthetic span file with every way an edge can be found
```

Same split as `logkit`: the builder runs in the cluster venv; `tools/callgraph.py` has no
dependencies so it can be copied into a blueprint's `tools/` folder.

## How an edge is found

| Order | Source | Needed for |
|---|---|---|
| 1 | **span link**: the callee's SERVER or CONSUMER span names the caller's span as its parent | callers that address a peer by IP (Train Ticket, through its registry) |
| 2 | **attribute**: the caller's CLIENT or PRODUCER span names the peer (`server.address`, `peer.service`, `net.peer.name`, `messaging.system`) | callees that write no spans: databases, brokers, proxies |
| 3 | **address**: an IP, resolved through other spans to it; else kept as `ip:<address>` | the rest |

Each edge keeps how it was found (`via`) and the database products its spans name (`db`), so a
proxy such as Train Ticket's `toxiproxy` still points at `mysql`.

## What it cannot see, and says so

- **Services that write no spans** (Sock Shop: edge-router, user, payment, the databases) appear
  only as callees. `callgraph.py` prints their callees as "unknown (writes no spans)".
- **Traced services with no outgoing span** (Sock Shop's catalogue: its database calls are not
  traced) print "unknown (no outgoing spans)", never "none".
- **A run without spans** gives a graph with `source: null`; the tool prints `NO SPANS`.
- Partner hosts have no spans. There the graph will have to come from the kernel's own TCP
  connections (not built).

## Run it

```bash
cd Blueprint
python -m spankit.build <run_dir> --out-dir <dir>                # -> <dir>/<run_id>.callgraph.json
python spankit/tools/callgraph.py <dir>/<run_id>.callgraph.json
python spankit/tools/callgraph.py <graph> --around front-end
python -m pytest spankit/tests logkit/tests
ruff check --config spankit/ruff.toml spankit
```

The sample Sock Shop run (1.35 M spans, 768 MB) takes about 18 s on a laptop.
