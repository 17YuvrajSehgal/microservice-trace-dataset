#!/bin/bash
# One-shot VM provisioning for the StrataTrace collection rig.
#
# Encodes the exact known-good sequence proven on GCP Ubuntu 24.04
# (2026-07-28). Run once on a fresh VM after cloning the repo:
#
#   git clone --recursive https://github.com/17YuvrajSehgal/microservice-trace-dataset.git
#   ./microservice-trace-dataset/microservice-lttng-data-collection-scripts/vm_bootstrap.sh
#
# Idempotent enough to re-run. After it finishes, run one gate:
#   ./run_gate.sh gate01
# and expect all six audit lines OK. See TROUBLESHOOTING.md for known issues.
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$SD/.." && pwd)

echo "=== [1/5] apt packages (LTTng 2.15 + toolchain) ==="
sudo add-apt-repository -y ppa:lttng/stable-2.15 || true
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    lttng-tools lttng-modules-dkms python3-lttngust babeltrace2 \
    stress-ng jq gh git curl python3 \
    python3-matplotlib
# python3-matplotlib is NOT optional despite verify_injection treating it as such.
# v1 evidence: Sock Shop asked for --plot on all 50 runs and produced ZERO images, because
# this package was missing and the plotting code swallowed the ImportError in silence. Train
# Ticket ran on a machine that happened to have it and produced 40. The verification image is
# the human-readable proof that a fault actually took effect, and it cannot be regenerated
# after the campaign - Prometheus data is not kept.

# LTTNG KERNEL MODULES: build, then REGISTER, then PROVE they load.
#
# Measured on the v2 VM (kernel 6.17.0-1022-gcp, 2026-09-04): dkms compiled and installed all
# 44 modules and reported "installed", yet `modprobe lttng-tracer` failed with
#   FATAL: Module lttng-tracer not found in directory /lib/modules/6.17.0-1022-gcp
# and `lttng list --kernel` returned "Failed to list Linux kernel tracepoints".
#
# The build was fine. The module index was stale - dkms had dropped the .ko files into
# updates/dkms/ without a depmod. One `depmod -a` fixed it and all 233 tracepoints appeared.
#
# Worth doing loudly rather than assuming: without kernel modules there is NO kernel tracing,
# which is the entire dataset. Failing here is cheap; failing mid-campaign is not.
echo "--- registering LTTng kernel modules ---"
sudo depmod -a
if sudo modprobe lttng-tracer 2>/dev/null; then
    n_events=$(sudo lttng list --kernel 2>/dev/null | wc -l)
    echo "    lttng-tracer loaded; $n_events kernel tracepoints available"
    [ "$n_events" -lt 100 ] && echo "    ** WARNING: expected ~230 tracepoints, got $n_events **"
else
    echo "    *** FATAL: lttng-tracer will not load on kernel $(uname -r)."
    echo "    *** There is no kernel tracing without it, so collection cannot start."
    echo "    *** Check: sudo dkms status ; sudo find /lib/modules/\$(uname -r) -name 'lttng*'"
    exit 1
fi

echo "=== [2/5] Docker (official get.docker.com; 27+ with compose v2) ==="
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$(whoami)"

# Docker 29 defaults to the containerd-snapshotter ("overlayfs") image store,
# which cAdvisor 0.49 cannot read - it fails to resolve container->service
# names, leaving the metrics modality with only unlabeled cgroup ids. Revert
# to the classic overlay2 store (cAdvisor-compatible, and the standard,
# reproducible choice). Requires a docker restart; images are rebuilt below.
if ! grep -q "containerd-snapshotter" /etc/docker/daemon.json 2>/dev/null; then
    echo '{ "features": { "containerd-snapshotter": false } }' | sudo tee /etc/docker/daemon.json >/dev/null
    sudo systemctl restart docker
    sleep 3
fi
echo "docker storage driver: $(sudo docker info -f '{{.Driver}}')"

echo "=== [3/5] verify LTTng kernel modules build against this kernel ==="
sudo modprobe lttng-tracer && echo "lttng-tracer OK" || {
    echo "ERROR: lttng-modules failed to load - check dkms status"; exit 1; }

echo "=== [4/5] build the two Tier-1 instrumented images ==="
cd "$HOME"
if [[ ! -d front-end ]]; then
    git clone -q -b otel-instrumentation https://github.com/17YuvrajSehgal/front-end.git
fi
sg docker -c "docker build -q -t frontend-otel:phase0 $HOME/front-end/" && echo "frontend-otel:phase0 OK"
if [[ ! -d catalogue ]]; then
    git clone -q -b otel-instrumentation https://github.com/17YuvrajSehgal/catalogue.git
fi
sg docker -c "docker build -q -f $HOME/catalogue/docker/catalogue/Dockerfile -t catalogue-otel:phase0 $HOME/catalogue/" && echo "catalogue-otel:phase0 OK"

echo "=== [5/5] bring up the 7-file stack ==="
export TRACE_SCRIPTS_DIR="$SD"
mkdir -p "$SD/otlp-out"
CD="$REPO/microservices-demo/deploy/docker-compose"
sg docker -c "cd $CD && COMPOSE_COMPATIBILITY=true docker compose \
    -f docker-compose.yml \
    -f docker-compose.monitoring.yml \
    -f $SD/docker-compose.metrics.yml \
    -f $SD/docker-compose.otel.yml \
    -f $SD/docker-compose.frontend-otel.yml \
    -f $SD/docker-compose.catalogue-otel.yml \
    -f $SD/docker-compose.toxiproxy.yml up -d"

echo "=== waiting 30s for services to become healthy ==="
sleep 30
FE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 http://localhost:80/ || echo 000)
PR=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://localhost:9090/api/v1/query?query=up" || echo 000)
echo "front-end:80 = $FE   prometheus:9090 = $PR"
[[ "$FE" == "200" && "$PR" == "200" ]] && echo "BOOTSTRAP OK - run ./run_gate.sh gate01" \
    || echo "BOOTSTRAP INCOMPLETE - see TROUBLESHOOTING.md (edge-router/prometheus port checks)"

echo "NOTE: log out and back in (or run 'newgrp docker') so docker group membership applies to your shell."
