#!/bin/bash
# Build the image every workload container runs. Idempotent; safe to re-run.
#
# The workloads used stock `python:3.12-slim` until conn_pool_exhaustion had to actually LOG IN
# to MySQL rather than just open a socket. Baking the driver in means the campaign never
# pip-installs anything per run - 300+ runs each fetching the same package over the network is
# a slow step that can only fail.
#
#   bash faults/build_workload_image.sh
set -euo pipefail
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMG="${WORKLOAD_IMAGE:-stratatrace-workload:v1}"

echo "== building $IMG =="
docker build -q -t "$IMG" "$SD/workloads"

# PROVE it, rather than trust that a successful build means a usable image. A missing driver
# would not surface until a fault ran mid-campaign and injected nothing.
if docker run --rm "$IMG" python3 -c "import pymysql, cryptography; print('pymysql', pymysql.__version__)"; then
    echo "== $IMG ready =="
else
    echo "*** $IMG built but cannot import its driver - conn_pool_exhaustion would inject nothing"
    exit 1
fi
