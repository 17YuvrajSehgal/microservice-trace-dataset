"""Synthetic runs in the docker_compose layout, with a known fault and a known healthy twin.

    T0        2026-09-05 15:18:40 UTC
    catalogue logfmt (go-kit): 5 List requests per second, took=1ms; from +100 s took=50ms
    front-end 1 "payment declined" 406 error per second all run long (a healthy baseline error);
              from +80 s, 5 "connect ECONNREFUSED" errors per second
    orders    Spring lines, plus OTel span-relay lines that must be skipped
    ground_truth.json and verification.json beside logs/, which nothing may read
The healthy twin has the same lines without the two faults.
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))      # Blueprint/, for `import logkit`

T0 = 1788621520          # 2026-09-05T15:18:40Z
SPAN = 200
FAULT_NEW_AT = 80
FAULT_LAT_AT = 100


def _ts(t: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%09dZ" % int(round((t % 1) * 1e9))


def write_run(root: Path, name: str, fault: bool) -> Path:
    run = root / name
    logs = run / "logs"
    logs.mkdir(parents=True)
    cat, fe, orders = [], [], []
    for s in range(SPAN):
        t = T0 + s
        took = "50.2ms" if fault and s >= FAULT_LAT_AT else "1.27ms"
        for k in range(5):
            cat.append(f"{_ts(t + k * 0.1)} ts={_ts(t + k * 0.1)} caller=logging.go:56 method=List "
                       f"tags= order=id pageNum=1 pageSize=10 result={k} err=null took={took}")
        fe.append(f"{_ts(t + 0.5)} Order response: {{\"status\":406,\"error\":\"Not Acceptable\","
                  f"\"message\":\"Payment declined: amount exceeds 100.00\"}}")
        if fault and s >= FAULT_NEW_AT:
            for k in range(5):
                fe.append(f"{_ts(t + 0.6 + k * 0.05)} Error: connect ECONNREFUSED 172.18.0.{k}:80")
        orders.append(f"{_ts(t + 0.2)} 2026-09-05 15:18:47.970  INFO [orders,551272cedb25096a,"
                      f"c9db4749dfa06ec0,false] 7 --- [nio-80-exec-1] w.w.s.o.c.OrdersController : "
                      f"Sending payment request {s}")
        orders.append(f"{_ts(t + 0.3)} [otel.javaagent] INFO io.opentelemetry.exporter.logging."
                      f"LoggingSpanExporter - 'GET /orders' : {s:032x} {s:016x} SERVER")
    (logs / "docker-compose_catalogue_1.log").write_text("\n".join(cat) + "\n")
    (logs / "docker-compose_front-end_1.log").write_text("\n".join(fe) + "\n")
    with gzip.open(logs / "docker-compose_orders_1.log.gz", "wt") as fh:
        fh.write("\n".join(orders) + "\n")
    (logs / "docker-compose_orders-db_1.log").write_text("")
    (run / "ground_truth.json").write_text('{"fault": {"name": "SECRET_FAULT"}}')
    (run / "verification.json").write_text('{"verdict": "SECRET"}')
    return run


@pytest.fixture(scope="session")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    return {"fault": write_run(root, "synthetic_fault_r1", True),
            "normal": write_run(root, "synthetic_normal_r1", False)}


@pytest.fixture(scope="session")
def indexes(runs, tmp_path_factory):
    from logkit.index import build_index, write_index
    from logkit.profile import load_profile

    out = tmp_path_factory.mktemp("idx")
    prof = load_profile("docker_compose")
    paths = {}
    for k, run in runs.items():
        p = out / f"{run.name}.logidx.json.gz"
        write_index(build_index(run, prof), p)
        paths[k] = p
    return paths
