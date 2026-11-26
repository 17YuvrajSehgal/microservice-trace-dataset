"""A synthetic OTLP span file with every case the graph builder must handle."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))      # Blueprint/, for `import spankit`


def attr(key, value):
    return {"key": key, "value": {"stringValue": value}}


def batch(service, spans):
    return {"resourceSpans": [{"resource": {"attributes": [attr("service.name", service)]},
                               "scopeSpans": [{"scope": {"name": "x"}, "spans": spans}]}]}


def span(kind, sid="", parent="", *attrs):
    return {"traceId": "t", "spanId": sid, "parentSpanId": parent, "kind": kind,
            "attributes": list(attrs)}


def write_spans(run: Path) -> Path:
    """Who calls whom, and how the builder must find it:
        front-end -> catalogue  x4  span link (catalogue's SERVER spans name them as parent)
        front-end -> orders     x1  attribute only (orders' SERVER span is not in the file)
        orders    -> payment    x2  IP only, but payment's SERVER spans link back (Train Ticket's case)
        orders    -> ip:10.9.9.9    IP only, nothing names it
        carts     -> toxiproxy  x1  attribute; a proxy in front of mysql (db.system)
        shipping  -> rabbitmq   x1  PRODUCER naming the broker; queue-master CONSUMES from it
        catalogue, payment      no outgoing span: their callees are unknown
    """
    (run / "otlp").mkdir(parents=True)
    front_end = ([span(3, "c%d" % i, "", attr("server.address", "catalogue")) for i in range(4)]
                 + [span(3, "o1", "", attr("server.address", "orders"))] + [span(2)] * 3)
    orders = [span(3, "p1", "", attr("network.peer.address", "172.18.0.7")),
              span(3, "p2", "", attr("network.peer.address", "172.18.0.7")),
              span(3, "x1", "", attr("network.peer.address", "10.9.9.9")),
              span(3, "self", "", attr("server.address", "orders"))]
    lines = [
        '"spanId":"cut in the middle by the byte-offset slice"}]}]}',
        json.dumps(batch("catalogue", [span(2, "s%d" % i, "c%d" % i) for i in range(4)] + [span(2)])),
        json.dumps(batch("front-end", front_end)),
        json.dumps(batch("orders", orders)),
        json.dumps(batch("payment", [span(2, "q1", "p1"), span(2, "q2", "p2")])),
        json.dumps(batch("carts", [span(3, "d1", "", attr("server.address", "toxiproxy"),
                                        attr("db.system", "mysql"))])),
        json.dumps(batch("shipping", [span(4, "m1", "", attr("messaging.system", "rabbitmq"))])),
        json.dumps(batch("queue-master", [span(5, "m2", "", attr("messaging.system", "rabbitmq"))])),
        "",
    ]
    (run / "otlp" / "spans.jsonl").write_text("\n".join(lines))
    (run / "ground_truth.json").write_text('{"fault": {"name": "SECRET"}}')
    return run


@pytest.fixture
def run(tmp_path):
    return write_spans(tmp_path / "synthetic_r1")
