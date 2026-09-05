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
# SAME LTTng as the Sock Shop VM. The two applications are being compared, so a difference in
# tracer version would be a confound sitting underneath every result.
sudo add-apt-repository -y ppa:lttng/stable-2.15 || true
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  lttng-tools lttng-modules-dkms babeltrace2 liblttng-ust-dev python3-lttngust \
  stress-ng jq git curl python3-pip openjdk-11-jdk maven \
  python3-matplotlib >/dev/null
# python3-matplotlib is NOT optional despite verify_injection treating it as such. v1 asked
# for --plot on all 50 Sock Shop runs and produced ZERO images: the package was missing and
# the plotting code swallowed the ImportError in silence. Train Ticket ran on a machine that
# happened to have it and produced 40. The verification image is the human-readable proof that
# a fault took effect, and it cannot be regenerated later - Prometheus data is not kept.
pip3 install -q --break-system-packages pandas pyarrow requests 2>/dev/null || true

echo "== [2/6] Docker + overlay2 (cAdvisor 0.49 can't read the containerd snapshotter store) =="
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sudo sh; fi
echo '{ "features": { "containerd-snapshotter": false } }' | sudo tee /etc/docker/daemon.json >/dev/null
sudo systemctl restart docker; sleep 3
sudo usermod -aG docker "$USER" || true

# LTTNG KERNEL MODULES: build, then REGISTER, then PROVE they load.
#
# This used to be `modprobe || echo "(deferred)"`, which is not a check - it prints a note and
# carries on with no kernel tracing at all, which is the entire dataset.
#
# Measured on stratatrace-ss (kernel 6.17.0-1022-gcp, 2026-09-04): dkms compiled and installed
# all 44 modules and reported "installed", yet modprobe failed with "Module lttng-tracer not
# found" and `lttng list --kernel` returned "Failed to list Linux kernel tracepoints". The
# build was fine; the module index was stale, because dkms dropped the .ko files into
# updates/dkms/ without a depmod. One `depmod -a` fixed it and all 233 tracepoints appeared.
#
# Failing here is cheap. Failing mid-campaign is not.
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

echo "== [3/6] OTel Java agent jar (copy from the Sock Shop agents dir; same repo) + jaxb-api =="
mkdir -p "$TT_SCRIPTS_DIR/agents" "$TT_SCRIPTS_DIR/otlp-out"
if [ ! -f "$TT_SCRIPTS_DIR/agents/opentelemetry-javaagent.jar" ]; then
  cp "$STRATA_REPO/microservice-lttng-data-collection-scripts/agents/opentelemetry-javaagent.jar" \
     "$TT_SCRIPTS_DIR/agents/" 2>/dev/null || \
  curl -fsSL -o "$TT_SCRIPTS_DIR/agents/opentelemetry-javaagent.jar" \
     https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.25.0/opentelemetry-javaagent.jar
fi
# jaxb-api: TT (jjwt 0.9.x) calls javax.xml.bind.DatatypeConverter, removed in JDK 11 ->
# NoClassDefFoundError on the write path (preserve/pay). The otel overlay puts this jar on the
# service boot classpath via -Xbootclasspath/a:/otel/jaxb-api.jar.
[ -f "$TT_SCRIPTS_DIR/agents/jaxb-api.jar" ] || curl -fsSL -o "$TT_SCRIPTS_DIR/agents/jaxb-api.jar" \
  https://repo1.maven.org/maven2/javax/xml/bind/jaxb-api/2.3.1/jaxb-api-2.3.1.jar

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
# toxiproxy loads AFTER dbenv so its *_MYSQL_HOST=toxiproxy repoint wins (mysql -> toxiproxy);
# it stays in-path for EVERY run (incl. normal) so scenarios stay comparable.
OVERLAYS="-f docker-compose.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.nacos.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.dbenv.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.toxiproxy.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.metrics.yml \
  -f $TT_SCRIPTS_DIR/docker-compose.otel.yml"
sg docker -c "docker compose $OVERLAYS up -d" || docker compose $OVERLAYS up -d

echo "== health-check (allow ~3-5 min: nacos+mysql first, then ~40 JVMs register & connect) =="
for i in $(seq 1 30); do
  ui=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null || echo 000)
  pr=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:9090/-/ready 2>/dev/null || echo 000)
  echo "  t+$((i*10))s: ts-ui-dashboard=$ui prometheus=$pr running=$(docker ps -q | wc -l)"
  [ "$ui" = 200 ] && [ "$pr" = 200 ] && { echo "  static UP"; break; }
  sleep 10
done

# The ui-dashboard nginx resolves ts-gateway-service ONCE at load; the gateway takes ~70 s to
# boot (JVM + nacos) so nginx caches a dead/absent IP -> 502 on /api/v1. Restart the ui-dashboard
# after the gateway is up so nginx re-resolves. (Any redeploy that recreates the gateway needs
# this too - it gets a new container IP.)
echo "== waiting for gateway, then restarting ui-dashboard to refresh its nginx DNS =="
for i in $(seq 1 24); do
  docker logs "${COMPOSE_PROJECT_NAME}_ts-gateway-service_1" 2>&1 | grep -q "Started GatewayApplication" && break
  sleep 5
done
docker restart "${COMPOSE_PROJECT_NAME}_ts-ui-dashboard_1" >/dev/null 2>&1 || true
sleep 8

echo "== API gate: real login through nginx -> gateway -> auth -> MySQL =="
for i in $(seq 1 12); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/api/v1/users/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"fdse_microservice","password":"111111"}' 2>/dev/null || echo 000)
  echo "  login attempt $i: HTTP $code"
  [ "$code" = 200 ] && { echo "  API UP (login 200)"; break; }
  sleep 10
done
# CORRECTED 5 Sept: this used to say "Next: seed TT data (empty DBs -> search returns [])".
# It is not true on this deployment and it cost a wrong status report. The services self-seed
# through their own InitData classes on first boot against the per-service databases that
# tt-init.sql creates. Verified on a fresh stack: login returns a token, trips/left returns
# D1345 shanghai->suzhou with prices, and the databases hold 13 stations, 72 route rows,
# 10 prices, 5 travels.
#
# There is nothing to seed. If a future stack really does come up empty, the symptom is
# `--probe` returning `"data":[]` from trips/left - check that first rather than assuming.
echo "== done. Verify with: python3 load_generator.py --host http://localhost:8080 --probe =="
echo "==       then the alignment gate. TT self-seeds; empty DBs would show as trips/left []. =="

echo "== workload image for the fault recipes =="
# Every co-located fault workload runs in this image. Built here so no campaign run ever has to
# pip-install anything: 300+ runs each fetching the same package over the network is a slow step
# that can only fail.
bash "$STRATA_REPO/microservice-lttng-data-collection-scripts/faults/build_workload_image.sh"
