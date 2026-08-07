"""
service_map — map a kernel event's (pid/TGID, procname) to a **microservice**.

Raw `procname` is a poor service key: several services share a comm (the carts/orders/shipping
JVMs are all "java"; catalogue/payment/user are all "app"), and the trace is full of kernel
threads (kswapd0, ksoftirqd/N, kworker, N_scheduler) that aren't services at all — keying on
procname alone yielded 229 noisy "services" on a real run.

Two-tier resolution (exact first, then fallback):
  1. **TGID identity** — the container's main PID (from the docker-top snapshot in meta/) is the
     TGID shared by all that container's threads, and kernel events carry pid = TGID. So a
     {TGID -> service} map built from meta/ attributes every containerized thread EXACTLY,
     splitting same-comm services correctly. This is the identity `wait_attribution.py` uses.
  2. **procname classifier** — for pids not in any container (kernel/host threads): bucket
     kernel threads as "kernel", map a few unique host comms, else "system:<comm>".
"""
from __future__ import annotations

import glob
import os
import re

# ---------------------------------------------------------------------------------------------
# App profiles. Select with env STRATATRACE_APP (default "sockshop" — keeps the frozen v1
# behavior identical). Each profile supplies SERVICE_CONTAINER (service -> docker container
# basename in meta/top_<container>_1_*.txt) and COMM_SERVICE (fallback comm -> service).
# ---------------------------------------------------------------------------------------------

_SOCKSHOP_CONTAINER = {
    "catalogue": "docker-compose_catalogue", "catalogue-db": "docker-compose_catalogue-db",
    "front-end": "docker-compose_front-end", "payment": "docker-compose_payment",
    "orders": "docker-compose_orders", "orders-db": "docker-compose_orders-db",
    "user": "docker-compose_user", "user-db": "docker-compose_user-db",
    "carts": "docker-compose_carts", "carts-db": "docker-compose_carts-db",
    "shipping": "docker-compose_shipping", "queue-master": "docker-compose_queue-master",
    "rabbitmq": "docker-compose_rabbitmq", "session-db": "docker-compose_session-db",
    "toxiproxy": "docker-compose_toxiproxy",
}
_SOCKSHOP_COMM = {
    "stress-ng": "aggressor", "stress-ng-vm": "aggressor", "stress-ng-cpu": "aggressor",
    "stress-ng-hdd": "aggressor", "traefik": "edge-router",
}
# service -> process comm (L2 fallback identity when a container has no docker-top snapshot)
_SOCKSHOP_SVC_COMM = {
    "catalogue": "app", "catalogue-db": "mysqld", "front-end": "node",
    "payment": "app", "user": "app", "toxiproxy": "toxiproxy",
    "carts": "java", "orders": "java", "shipping": "java", "queue-master": "java",
}

# Train Ticket (FudanSELab). Compose project name = "trainticket" (COMPOSE_PROJECT_NAME set in
# the deploy command) + COMPOSE_COMPATIBILITY -> containers "trainticket_<svc>_1". 40 app
# services (39 Java Spring Boot ts-*-service incl. the Spring Cloud gateway; the ui-dashboard
# is JS), one shared MySQL 8, redis, nacos for discovery.
#
# NO MongoDB: TT's source migrated every service to MySQL (jdbc:mysql://ts-*-mysql); the compose's
# 24 ts-*-mongo were dead artifacts (preserve's mongo config is even commented out). Our deploy
# drops them and runs ONE shared mysql:8 (docker-compose.dbenv.yml) with a per-service database +
# nacos (docker-compose.nacos.yml). ts-voucher-service (Python) keeps its own ts-voucher-mysql.
_TT_JAVA = [
    "ts-admin-basic-info-service", "ts-admin-order-service", "ts-admin-route-service",
    "ts-admin-travel-service", "ts-admin-user-service", "ts-assurance-service", "ts-auth-service",
    "ts-basic-service", "ts-cancel-service", "ts-config-service",
    "ts-consign-price-service", "ts-consign-service", "ts-contacts-service", "ts-execute-service",
    "ts-food-service", "ts-gateway-service", "ts-inside-payment-service", "ts-news-service",
    "ts-notification-service", "ts-order-other-service", "ts-order-service", "ts-payment-service",
    "ts-preserve-other-service", "ts-preserve-service", "ts-price-service", "ts-rebook-service",
    "ts-route-plan-service", "ts-route-service", "ts-seat-service", "ts-security-service",
    "ts-station-service", "ts-ticket-office-service", "ts-train-service",
    "ts-travel-plan-service", "ts-travel-service", "ts-travel2-service", "ts-user-service",
    "ts-verification-code-service", "ts-voucher-service",
]
# compose-named (project prefix + _1); JS/Python/DB containers off the Java path
_TT_OTHER = ["ts-ui-dashboard", "ts-voucher-mysql", "redis"]
_TT_PROJECT = os.environ.get("TT_COMPOSE_PROJECT", "trainticket")
_TRAINTICKET_CONTAINER = {s: f"{_TT_PROJECT}_{s}" for s in (_TT_JAVA + _TT_OTHER)}
# our overlay infra sets an explicit container_name (no project prefix / _1 suffix)
_TRAINTICKET_CONTAINER.update({"mysql": "mysql", "nacos": "nacos"})
_TRAINTICKET_COMM = {
    "stress-ng": "aggressor", "stress-ng-vm": "aggressor", "stress-ng-cpu": "aggressor",
    "stress-ng-hdd": "aggressor",
}
_TRAINTICKET_SVC_COMM = {
    **{s: "java" for s in _TT_JAVA},
    "mysql": "mysqld", "ts-voucher-mysql": "mysqld", "nacos": "java",
    "ts-ui-dashboard": "node", "redis": "redis-server",
}

_PROFILES = {
    "sockshop": (_SOCKSHOP_CONTAINER, _SOCKSHOP_COMM, _SOCKSHOP_SVC_COMM),
    "trainticket": (_TRAINTICKET_CONTAINER, _TRAINTICKET_COMM, _TRAINTICKET_SVC_COMM),
}
_APP = os.environ.get("STRATATRACE_APP", "sockshop").lower()
if _APP not in _PROFILES:
    raise ValueError(f"STRATATRACE_APP={_APP!r} not in {list(_PROFILES)}")

# active profile (module-level; the derivers read these)
SERVICE_CONTAINER, COMM_SERVICE, SERVICE_COMM = _PROFILES[_APP]

# kernel / system threads -> bucketed as "kernel" (never a microservice)
_KERNEL_RE = re.compile(
    r"^(kswapd\d+|ksoftirqd|migration|rcu_|rcuop|rcuos|rcub|kworker|watchdog|khugepaged|"
    r"kcompactd|kdevtmpfs|kauditd|ksmd|oom_reaper|kblockd|kthreadd|kintegrityd|jbd2|"
    r"ext4|xfs|scsi_|kthrotld|khungtaskd|netns|kstrp|cpuhp|idle_inject|irq/|mmcqd|"
    r"kswork|kpsmoused|kstrp|kswapd|kverityd|kdmflush|dm-|md\d|raid|nvme|kaluad|"
    r"\d+_scheduler|swapper|systemd-udevd|systemd-journal|systemd-network|systemd-resolve)"
)


def is_kernel_thread(comm: str) -> bool:
    if not comm:
        return False
    return bool(_KERNEL_RE.match(comm)) or comm.startswith("[")


def container_pids(meta_dir: str, container: str) -> set:
    """ALL host PIDs (== TGIDs) of a container's processes from its docker-top start snapshot.
    Not just PID 1: services with a shell-wrapper entrypoint (Sock Shop's `java.sh`) run PID 1
    = the shell and the real service as its java child under a different TGID — the service's
    threads carry that child TGID, so both must map to the service."""
    pids: set = set()
    for pat in (f"top_{container}_1_start.txt", f"top_{container}_1_*.txt", f"top_*{container}*start*.txt"):
        for path in sorted(glob.glob(os.path.join(meta_dir, pat))):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    hdr = f.readline().split()
                    try:
                        c = [h.upper() for h in hdr].index("PID")
                    except ValueError:
                        continue
                    for line in f:
                        p = line.split()
                        if len(p) > c and p[c].isdigit():
                            pids.add(int(p[c]))
            except OSError:
                continue
        if pids:
            break
    return pids


def build_tgid_service(meta_dir: str) -> dict:
    """Return {tgid: service} from every container's docker-top snapshot in meta_dir —
    mapping ALL of each container's PIDs (shell + runtime child) to its service."""
    out = {}
    for service, container in SERVICE_CONTAINER.items():
        for pid in container_pids(meta_dir, container):
            out[pid] = service
    return out


def classify(pid, procname, tgid_service: dict, collapse_system: bool = False) -> str:
    """Resolve a microservice for an event. Exact TGID map first, then procname fallback.

    collapse_system: fold every non-container host process (dockerd, containerd, host CLI
    tools, stray java/python, …) into a single `system` bucket instead of `system:<comm>`.
    This gives clean study tables (~13 microservices + `kernel` + `system`) — the raw kernel
    trace otherwise yields 100+ `system:<comm>` labels that are all non-service host noise.
    `kernel` (kswapd/ksoftirqd/… — meaningful, e.g. the F3 reclaim actor) stays separate."""
    if tgid_service:
        svc = tgid_service.get(pid)
        if svc is not None:
            return svc
    if is_kernel_thread(procname):
        return "kernel"
    if procname in COMM_SERVICE:
        return COMM_SERVICE[procname]
    return "system" if collapse_system else f"system:{procname}"
