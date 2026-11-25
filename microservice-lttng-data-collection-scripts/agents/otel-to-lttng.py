#!/usr/bin/env python3
import argparse
import json
import subprocess
import re
import lttngust.loghandler
import logging
import select
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--quiet", action="store_true", help="Suppress printing spans to stdout")
args = parser.parse_args()

logger = logging.getLogger("otel.spans")
logger.handlers.clear()
lttng_handler = lttngust.loghandler._Handler()
logger.addHandler(lttng_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# Matches OTel Java agent LoggingSpanExporter output
span_pattern = re.compile(
    r"\[otel\.javaagent.*?\]\s+INFO.*?LoggingSpanExporter - '(.+?)' : ([a-f0-9]+) ([a-f0-9]+) (\w+)"
)

# Docker logs --timestamps prefix, e.g. 2026-03-23T12:34:56.123456789Z ...
docker_ts_pattern = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+(.*)$"
)

# WHICH CONTAINERS. Until 25-11-2026 this was a fixed list of four Sock Shop names, so on Train
# Ticket the relay followed nothing (0 of 134 v2 runs have a user-space trace). Now:
#   1. RELAY_CONTAINERS="name1,name2" if set;
#   2. else the four Sock Shop Java services, when they are running (unchanged behaviour there);
#   3. else every running container (Train Ticket and anything else). A container that prints
#      no span lines costs one idle `tail`.
# Path 3 has NOT been run on a Train Ticket VM yet.
import os


def running_containers():
    try:
        return subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"],
                                       stderr=subprocess.DEVNULL).decode().split()
    except Exception:
        return []


_up = running_containers()
_sock = {f"docker-compose_{s}_1": s for s in ["carts", "orders", "shipping", "queue-master"]}
if os.environ.get("RELAY_CONTAINERS"):
    containers = {c: c for c in os.environ["RELAY_CONTAINERS"].split(",") if c}
elif all(c in _up for c in _sock):
    containers = _sock
else:
    containers = {c: c for c in _up}
if not containers:
    print("[relay] WARN: no container to follow - the user-space trace will be empty",
          file=sys.stderr, flush=True)

procs = {}
stream_to_meta = {}

# HOW THE LOG IS READ. Until 25-11-2026 this followed `docker logs -f --tail=0`. That returns
# NOTHING once the container's log file has been truncated from outside, and
# campaign_finish_run.sh truncates every container log between runs (the files would fill the
# disk otherwise). Measured on the VM: 12,280 span lines in 6 s after a container restart, 0
# right after `truncate -s 0`, still 0 fifteen seconds later, while `docker logs --since` kept
# returning 20,000 lines. So the relay only worked in the first run after a container start:
# the user-space trace is empty in 37 of 40 v3 runs and in 137 of 170 v2 Sock Shop runs.
#
# `tail -F` on the json log file itself notices a truncation and carries on, so that is used.
# The file belongs to root, hence sudo. If that is not possible the old way is the fallback,
# and the relay says so.
def log_path(container):
    try:
        cid = subprocess.check_output(["docker", "inspect", "-f", "{{.Id}}", container],
                                      stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None
    path = f"/var/lib/docker/containers/{cid}/{cid}-json.log"
    ok = subprocess.call(["sudo", "-n", "test", "-r", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    return path if ok else None


for container, service in containers.items():
    path = log_path(container)
    if path:
        cmd, from_file = ["sudo", "-n", "tail", "-n", "0", "-F", path], True
    else:
        cmd, from_file = ["docker", "logs", "-f", "--tail=0", "--timestamps", container], False
        print(f"[relay] WARN: cannot read the log file of {container}; following `docker logs`, "
              f"which goes silent after a log truncation", file=sys.stderr, flush=True)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL if from_file else subprocess.STDOUT)
    procs[container] = p
    stream_to_meta[p.stdout] = {"container": container, "service": service, "from_file": from_file}

if not args.quiet:
    print("Relaying OTel spans to LTTng... (Ctrl+C to stop)")

try:
    while True:
        readable, _, _ = select.select(list(stream_to_meta.keys()), [], [], 1.0)
        for stream in readable:
            raw = stream.readline()
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            meta = stream_to_meta[stream]
            if meta["from_file"]:
                # one JSON object per line: {"log": "...\n", "stream": "stderr", "time": "...Z"}
                try:
                    rec = json.loads(line)
                    line = f'{rec.get("time", "")} {rec.get("log", "").strip()}'.strip()
                except ValueError:
                    continue
            service = meta["service"]
            container = meta["container"]

            docker_ts = ""
            m_ts = docker_ts_pattern.match(line)
            if m_ts:
                docker_ts, line = m_ts.groups()

            m = span_pattern.search(line)
            if not m:
                continue

            op, trace_id, span_id, kind = m.groups()
            relay_ts_ns = time.time_ns()

            # Keep op quoted in case it contains spaces
            safe_op = op.replace("\\", "\\\\").replace('"', '\\"')

            msg = (
                f'service={service} '
                f'container={container} '
                f'phase=export '
                f'docker_ts={docker_ts or "na"} '
                f'relay_ts_ns={relay_ts_ns} '
                f'trace_id={trace_id} '
                f'span_id={span_id} '
                f'kind={kind} '
                f'op="{safe_op}"'
            )

            logger.info(msg)

            if not args.quiet:
                print(f"[LTTng] {msg}")

except KeyboardInterrupt:
    if not args.quiet:
        print("Stopped.")
finally:
    for p in procs.values():
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs.values():
        try:
            p.wait(timeout=2)
        except Exception:
            pass