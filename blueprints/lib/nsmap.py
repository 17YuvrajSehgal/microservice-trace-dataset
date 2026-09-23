#!/usr/bin/env python3
"""Map pid_ns -> container name for a run, so the scorer can check WHERE properly.

WHY THIS IS NEEDED. `score_where` returned `container` for ANY pid_ns the agent mentioned:

    if _NS_RE.search(str(pred_service or "")):
        return {"where": "container", ...}

It never checked the namespace was the right one. That is fine while no blueprint tells the
agent to name a container, and dangerous the moment one does - "rank the containers and name
the lowest" would score as WHERE-right whether the ranking worked or not.

HOW, WITHOUT ANY NEW COLLECTION. The kernel trace records no service name, and `meta/` records
no namespace, so neither side can answer alone. But both measure CPU time:

    meta/cgroup_<container>_tick_*.txt   cpu.stat usage_usec, per CONTAINER
    dataset/index/<run>.tsv.gz           summed sched_stat_runtime ns, per PID_NS

Sort both by CPU consumed and the orders line up. Measured on svc_net_..._r1, every container
matched its namespace at a ratio of 1.09-1.10 - a systematic offset, because the cgroup ticks
start a little after the recorder and stop a little before it, exactly the gap documented in
ctf_tool.ctf_timespan. The offset is constant, so the RANKING is what carries the assignment.

This is scorer-side code. It reads ground truth's neighbourhood and must never be importable
from anything the agent can reach.

    python nsmap.py <run_dir>
"""
from __future__ import annotations
import collections, glob, gzip, os, re, sys

TAB = chr(9)
INDEX_ROOT = os.environ.get("CTF_INDEX_ROOT",
                            "/scratch/yuvraj17/stratatrace/dataset/index-v2")
_TICK = re.compile(r"cgroup_(.+)_tick_(\d{8}T\d{6}Z)\.txt$")
# the host's own namespace - not a container, and always the biggest CPU consumer because every
# unattributed kernel thread lands in it. Excluded before matching or it takes a container's slot.
HOST_NS = "4026531836"


def container_cpu(run_dir: str) -> dict:
    """Seconds of CPU per container, from the first and last cgroup snapshot."""
    usage = collections.defaultdict(dict)
    for f in glob.glob(os.path.join(run_dir, "meta", "cgroup_*_tick_*.txt")):
        m = _TICK.search(os.path.basename(f))
        if not m:
            continue
        name, stamp = m.group(1), m.group(2)
        try:
            for line in open(f, errors="replace"):
                if line.startswith("usage_usec"):
                    usage[name][stamp] = int(line.split()[1])
                    break
        except OSError:
            continue
    out = {}
    for name, d in usage.items():
        ks = sorted(d)
        if len(ks) >= 2 and d[ks[-1]] > d[ks[0]]:
            out[name] = (d[ks[-1]] - d[ks[0]]) / 1e6
    return out


def ns_cpu(run_id: str, index_root: str | None = None) -> dict:
    """Seconds of CPU per pid_ns, from the index's summed sched_stat_runtime."""
    p = os.path.join(index_root or INDEX_ROOT, run_id + ".tsv.gz")
    if not os.path.exists(p):
        return {}
    tot = collections.defaultdict(int)
    with gzip.open(p, "rt") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            f = line.rstrip(chr(10)).split(TAB)
            if len(f) >= 6 and f[1] == "sched_stat_runtime":
                tot[f[3]] += int(f[5])
    return {k: v / 1e9 for k, v in tot.items() if k != HOST_NS}


def build(run_dir: str, index_root: str | None = None) -> dict:
    """{'by_ns': {pid_ns: container}, 'by_container': {...}, 'ratios': [...]}.

    Rank-matched, not value-matched: the two clocks differ by a constant factor. The ratios are
    returned so a caller can see whether the assignment is trustworthy on this run - they should
    all be close to each other, and a spread means the ranks disagree somewhere.
    """
    run_id = os.path.basename(run_dir.rstrip("/"))
    c = sorted(container_cpu(run_dir).items(), key=lambda kv: -kv[1])
    n = sorted(ns_cpu(run_id, index_root).items(), key=lambda kv: -kv[1])
    by_ns, ratios = {}, []
    for (name, cv), (ns, nv) in zip(c, n):
        by_ns[ns] = name
        ratios.append(nv / cv if cv else 0.0)
    return {"run_id": run_id, "by_ns": by_ns,
            "by_container": {v: k for k, v in by_ns.items()},
            "ratios": ratios, "n_containers": len(c), "n_namespaces": len(n)}


def _service_matches(container_name: str, service: str) -> bool:
    """Compose names the container `docker-compose_carts_1`; ground truth names `carts`.

    Match on the delimited word, never a substring: `carts` must not match `carts-db`, and on
    Train Ticket `ts-basic-service` must not match `ts-basic-service-db`.
    """
    parts = re.split(r"[_.]", container_name.lower())
    return service.strip().lower() in parts


# How much closer the best CPU match must be than the runner-up before the assignment is
# believed. Rank-matching the whole ordering looked fine and was not: measured on
# tt_svc_net_..._r1, 27 of 41 adjacent containers sit within 15% of each other on CPU, so most
# of that ordering is a coin flip and the resulting map put the netem target at rank 4, 21 and 5
# on three runs. Sock Shop's busy containers separate cleanly (carts-db 266 s, front-end 158 s,
# carts 115 s) which is why it matched 3 of 3 there. So: resolve one container, demand that it
# is unambiguous, and return None otherwise. A scorer that says "cannot tell" is worth far more
# than one that quietly assigns the wrong name.
MARGIN = 1.25


def ns_for_service(run_dir: str, service: str, index_root: str | None = None):
    """The pid_ns of the container running `service`, or None when it cannot be resolved.

    Matches ONE container by CPU time rather than rank-matching the whole ordering, and refuses
    the answer unless the runner-up namespace is at least MARGIN times further away.
    """
    if not service:
        return None
    run_id = os.path.basename(run_dir.rstrip("/"))
    cc = container_cpu(run_dir)
    target = next((v for k, v in cc.items() if _service_matches(k, service)), None)
    if not target:
        return None
    nn = ns_cpu(run_id, index_root)
    if len(nn) < 2:
        return None
    # the two clocks differ by a constant factor; calibrate it from the whole run rather than
    # assuming the 1.1 measured on one Sock Shop trace
    scale = (sum(nn.values()) / sum(cc.values())) if sum(cc.values()) else 1.0
    want = target * scale
    ranked = sorted(nn.items(), key=lambda kv: abs(kv[1] - want))
    best, second = ranked[0], ranked[1]
    d1 = abs(best[1] - want) or 1e-9
    d2 = abs(second[1] - want)
    return best[0] if d2 / d1 >= MARGIN else None


if __name__ == "__main__":
    rd = sys.argv[1]
    m = build(rd)
    print("%s  (%d containers, %d namespaces)"
          % (m["run_id"], m["n_containers"], m["n_namespaces"]))
    for ns, name in sorted(m["by_ns"].items(), key=lambda kv: kv[1]):
        print("   %-14s %s" % (ns, name))
    r = m["ratios"]
    if r:
        print("   index/meta CPU ratios: %.2f-%.2f (should be tight)" % (min(r), max(r)))
