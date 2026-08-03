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

# service -> docker container basename in meta/top_<container>_1_*.txt (from the MVP engine)
SERVICE_CONTAINER = {
    "catalogue": "docker-compose_catalogue", "catalogue-db": "docker-compose_catalogue-db",
    "front-end": "docker-compose_front-end", "payment": "docker-compose_payment",
    "orders": "docker-compose_orders", "orders-db": "docker-compose_orders-db",
    "user": "docker-compose_user", "user-db": "docker-compose_user-db",
    "carts": "docker-compose_carts", "carts-db": "docker-compose_carts-db",
    "shipping": "docker-compose_shipping", "queue-master": "docker-compose_queue-master",
    "rabbitmq": "docker-compose_rabbitmq", "session-db": "docker-compose_session-db",
    "toxiproxy": "docker-compose_toxiproxy",
}

# unique host/aggressor comms with an unambiguous service mapping (fallback only)
COMM_SERVICE = {
    "stress-ng": "aggressor", "stress-ng-vm": "aggressor", "stress-ng-cpu": "aggressor",
    "stress-ng-hdd": "aggressor", "traefik": "edge-router",
}

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


def classify(pid, procname, tgid_service: dict) -> str:
    """Resolve a microservice for an event. Exact TGID map first, then procname fallback."""
    if tgid_service:
        svc = tgid_service.get(pid)
        if svc is not None:
            return svc
    if is_kernel_thread(procname):
        return "kernel"
    if procname in COMM_SERVICE:
        return COMM_SERVICE[procname]
    return f"system:{procname}"
