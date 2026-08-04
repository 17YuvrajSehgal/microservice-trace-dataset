#!/bin/bash
# vm_bootstrap_tt.sh — one-shot provisioner for the Train Ticket collector VM.
# Mirrors the Sock Shop vm_bootstrap.sh: installs LTTng/Babeltrace/Docker (+ the overlay2 fix
# cAdvisor needs), clones OUR TT fork, builds OUR images from source, brings up the instrumented
# stack (base + metrics + otel), and health-checks. Run on a fresh Ubuntu 24.04 VM.
#
#   export STRATA_REPO=~/microservice-trace-dataset      # this research repo (already cloned)
#   bash $STRATA_REPO/train-ticket-collection-scripts/vm_bootstrap_tt.sh
set -euo pipefail
STRATA_REPO="${STRATA_REPO:-$HOME/microservice-trace-dataset}"
TT_SCRIPTS_DIR="$STRATA_REPO/train-ticket-collection-scripts"
TT_DIR="${TT_DIR:-$HOME/train-ticket}"           # the fork clone = compose project dir
FORK="${FORK:-https://github.com/17YuvrajSehgal/train-ticket.git}"
export IMG_REPO="${IMG_REPO:-stratatrace-tt}" IMG_TAG="${IMG_TAG:-v1}"    # OUR image tags
export COMPOSE_PROJECT_NAME=trainticket COMPOSE_COMPATIBILITY=true

echo "== [1/6] apt: LTTng, Babeltrace2, stress-ng, JDK11+Maven (TT builds from source), tools =="
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  lttng-tools lttng-modules-dkms babeltrace2 liblttng-ust-dev python3-lttngust \
  stress-ng jq git curl python3-pip openjdk-11-jdk maven >/dev/null
pip3 install -q --break-system-packages pandas pyarrow requests 2>/dev/null || true

echo "== [2/6] Docker + overlay2 (cAdvisor 0.49 can't read the containerd snapshotter store) =="
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sudo sh; fi
echo '{ "features": { "containerd-snapshotter": false } }' | sudo tee /etc/docker/daemon.json >/dev/null
sudo systemctl restart docker; sleep 3
sudo usermod -aG docker "$USER" || true
sudo modprobe lttng-tracer 2>/dev/null || echo "  (lttng-tracer modprobe deferred)"

echo "== [3/6] OTel Java agent jar (copy from the Sock Shop agents dir; same repo) =="
mkdir -p "$TT_SCRIPTS_DIR/agents" "$TT_SCRIPTS_DIR/otlp-out"
if [ ! -f "$TT_SCRIPTS_DIR/agents/opentelemetry-javaagent.jar" ]; then
  cp "$STRATA_REPO/microservice-lttng-data-collection-scripts/agents/opentelemetry-javaagent.jar" \
     "$TT_SCRIPTS_DIR/agents/" 2>/dev/null || \
  curl -fsSL -o "$TT_SCRIPTS_DIR/agents/opentelemetry-javaagent.jar" \
     https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.25.0/opentelemetry-javaagent.jar
fi

echo "== [4/6] clone OUR TT fork, branch stratatrace (clean base: stock ts-common + jre-11, no"
echo "         LTTng-UST source tracing, no avatar; the prior LTTng work stays on master) =="
[ -d "$TT_DIR/.git" ] || git clone --recursive -b stratatrace "$FORK" "$TT_DIR"

echo "== [5/6] build OUR images from source (SLOW: mvn jars + docker, ~1-2 h first time) =="
cd "$TT_DIR"
# TT Dockerfiles do `ADD ./target/*.jar` -> jars MUST be built first (mvn), then imaged.
# -T 4 = 4 parallel modules (16 vCPU, keep RAM sane); -DskipTests for speed.
echo "  [5a] mvn clean package (41 modules, downloads ~/.m2 deps first run) ..."
mvn -q -T 4 clean package -DskipTests 2>&1 | tail -20 || { echo "MVN FAILED"; exit 1; }
echo "  [5b] docker compose build (package jars into OUR images) ..."
sg docker -c "docker compose build" || docker compose build

echo "== [6/6] bring up the instrumented stack (base + nacos + shared-mysql + metrics + otel) =="
# Overlay order (compose merges by service name, later wins): base app -> nacos (discovery +
# NACOS_ADDRS) -> dbenv (shared mysql:8 + per-service *_MYSQL_* env; the base compose ships no
# mongo now) -> metrics -> otel (java-agent injection). TT's compose alone can't boot: its source
# wants nacos+MySQL+gateway that the stock compose lacks - these overlays supply them.
export TT_SCRIPTS_DIR
OVERLAYS="-f docker-compose.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.nacos.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.dbenv.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.metrics.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.otel.yml"
sg docker -c "docker compose $OVERLAYS up -d" || docker compose $OVERLAYS up -d

echo "== health-check (allow ~3-5 min: nacos+mysql first, then ~40 JVMs register & connect) =="
for i in $(seq 1 30); do
  ui=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null || echo 000)
  pr=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:9090/-/ready 2>/dev/null || echo 000)
  echo "  t+$((i*10))s: ts-ui-dashboard=$ui prometheus=$pr running=$(docker ps -q | wc -l)"
  [ "$ui" = 200 ] && [ "$pr" = 200 ] && { echo "  STACK UP"; break; }
  sleep 10
done
echo "== done. Next: load_generator.py --probe to validate the TT API, then run the alignment gate. =="
