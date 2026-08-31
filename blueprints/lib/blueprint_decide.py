#!/usr/bin/env python3
"""Apply the blueprints' decision rules to an L0 evidence pack. No model involved.

This is the blueprint arm of the comparison. It reads the SAME evidence pack every other
method gets, applies the rules written in the blueprints, and returns a verdict in the same
shape the LLM methods return, so one scorer can grade them all.

Every blueprint is offered every incident. Whichever fires is the answer; if several or none
fire that is recorded rather than resolved by a coin flip, so this tests SELECTION as well as
accuracy.

WHAT CHANGED (2026-08-29, findings F1-F3)
-----------------------------------------
The old version decided the CPU family on RUNQUEUE DELAY. Measurement killed that: runqueue
delay is raised in every CPU-family fault AND in healthy load bursts, and its ordering is
inverted against severity (host saturation 52x, cgroup cap 15.7x, co-tenant 7.1x, healthy
burst 3.7x). Deciding on it gave a 42-62% false-positive rate, including a healthy system
reported as a host fault at 0.80 confidence.

The deciding signal is now HOST CPU UTILISATION from sched_switch, which was measured to
split the four CPU families with no overlap across 17 labelled runs:

    host saturation   util 0.991-0.998   newcomer takes 6.54-6.62 cores
    co-tenant         util 0.619-0.681   newcomer takes 0.99-2.00 cores
    healthy           util 0.462-0.531   4/5 have no newcomer
    cgroup cap        util 0.114-0.365   no newcomer, utilisation FALLS

Runqueue delay is kept and reported, but only as corroboration.

    python3 blueprint_decide.py --pack <pack.json> [--out verdict.json]
"""
from __future__ import annotations
import argparse, json, os, sys

# ---- thresholds, every one of them measured; see evidence/cpu_cluster_separation.json ----
SATURATED = 0.95        # host saturation measured 0.991-0.998; next family down tops out at 0.681
COLLAPSE_RATIO = 0.80   # cap runs fell to 0.25-0.73 of baseline; healthy runs sat at 1.04-1.15
THIEF_CORES = 0.50      # co-tenant newcomers took 0.988-2.002; the largest healthy one was 0.296
CONTENDED = 0.55        # co-tenant utilisation floor 0.619; healthy ceiling 0.531
BIG_THIEF = 4.0         # host-saturation newcomers took 6.54-6.62; co-tenant never above 2.002
LOSER_CORES = -0.30     # cap runs lost 0.357-0.876; healthy and co-tenant lost 0.024-0.160

BLOCK_X = 5.0           # datastore fault measured 36.8x; its control 1.12x

# ---- the two checks that fix the datastore rule's false fires (finding F13/F15) ----
# The rule fires on socket blocking alone, which every impostor also trips. Two additions,
# both measured across 40 runs on two applications.
#
# 1. RETRANSMISSION VETO. A network fault is the only family that drops packets, so heavy
#    retransmission means the problem is the path, not the datastore. Measured: network
#    18.5-60.7%, slow datastore never above 7.14%, every other family at or near 0. A cut at
#    12 sits 1.7x above the datastore ceiling and 1.5x below the network floor.
RETRANS_VETO_PCT = 12.0
#
# 2. THE DATASTORE MUST ACTUALLY BE SLOW. Blocking says a process is waiting; endpoint
#    slowdown says something is answering slowly. MEASURED on the first application: slow
#    datastore 38.60-47.57x against a 8.58x ceiling for every non-network family, so 18 sits
#    at the geometric midpoint with 2.1x margin on both sides.
#    HONEST COST: on the second application the datastore fault reaches only 9.75x on two of
#    four runs, so this gate loses them, and a memory-cap fault there reaches 221-225x so the
#    gate does not help. It is applied because the net effect is measured to be strongly
#    positive, not because it is universal - see the blueprint scenario.
ENDPOINT_SLOWDOWN_MIN = 18.0
RQ_X = 2.0              # "runqueue is raised at all" - used only to describe a run, never
                        # to decide anything.

# "the threads are genuinely SHORT of CPU" is a different and much stronger claim, and it
# needs its own bar. MEASURED across 22 slow-datastore and cgroup-cap runs on both apps:
#     slow datastore   runqueue 1.04-2.59   (never above 2.6 on either app)
#     cgroup cap       runqueue 13.54-29.17 (on the app where it produces a signal at all)
# A 2.0 cut sits inside the datastore range and misdiagnosed two Train Ticket datastore runs
# as throttling. 5.0 leaves margin on both sides - 1.9x above the datastore ceiling and 2.7x
# below the cap floor - rather than being placed next to any single run.
STARVED_RQ_X = 5.0

SOCKET_CALLS = ("poll", "epoll_wait", "epoll_pwait", "recvfrom", "recvmsg", "read", "select")
INFRA = ("kworker", "ksoftirqd", "rcu_", "kswapd", "kcompactd", "migration", "watchdog",
         "systemd", "containerd", "dockerd", "cadvisor", "prometheus", "node_export",
         "google_guest", "runc", "sshd", "irq/")


def is_infra(name):
    n = (name or "").lower()
    return any(k in n for k in INFRA)


def _rq(pack):
    """Runqueue statistics. Corroboration only; no rule may decide on these."""
    rows = pack.get("runqueue_delay", {}).get("top_by_inflation", [])
    xs = [r["p95_x"] for r in rows if r.get("p95_x")]
    if not xs:
        return {"max": None, "median": None, "n_inflated": 0, "worst_app": None}
    return {
        "max": max(xs),
        "median": sorted(xs)[len(xs) // 2],
        "n_inflated": sum(1 for x in xs if x >= RQ_X),
        "worst_app": next((r["service"] for r in rows
                           if r.get("p95_x", 0) >= RQ_X and not is_infra(r["service"])), None),
    }


def _cpu(pack):
    """On-CPU attribution: the deciding evidence for the whole CPU family."""
    s = (pack.get("oncpu") or {}).get("signature") or {}
    ub, ui = s.get("host_util_baseline"), s.get("host_util_incident")
    return {
        "available": ub is not None and ui is not None,
        "util_baseline": ub,
        "util_incident": ui,
        "util_ratio": round(ui / ub, 3) if (ub and ui is not None) else None,
        "thief_comm": s.get("thief_comm"),
        "thief_cores": s.get("thief_cores_gained") or 0.0,
        "loser_comm": s.get("biggest_loser_comm"),
        "loser_cores": s.get("biggest_loser_cores") or 0.0,
        "n_cpus": s.get("n_cpus"),
    }


def _net(pack):
    """Packet loss, and how slowly service endpoints answer. Either may be absent from a
    pack built before these measurements existed, and absent is reported as absent - the
    rules below treat an unavailable check as 'not applied' rather than as passing."""
    nl = (pack.get("netloss") or {}).get("signature") or {}
    ep = (pack.get("endpoints") or {}).get("signature") or {}
    slowest = ep.get("slowest") or {}
    return {
        "retrans_available": nl.get("worst_retrans_pct") is not None,
        "worst_retrans_pct": nl.get("worst_retrans_pct"),
        "n_impaired_ifaces": nl.get("n_impaired"),
        "endpoint_available": slowest.get("p95_x") is not None,
        "worst_endpoint_x": slowest.get("p95_x"),
        "worst_endpoint": slowest.get("endpoint"),
        "n_endpoints_slowed": ep.get("n_slowed_2x"),
    }


def _blk(pack):
    rows = pack.get("blocking_syscall", {}).get("top_by_inflation", [])
    sock = [r for r in rows
            if r.get("p95_x")
            and r["comm_syscall"].split("|")[-1] in SOCKET_CALLS
            and not is_infra(r["comm_syscall"].split("|")[0])]
    sock.sort(key=lambda r: -r["p95_x"])
    return {"rows": rows, "socket_hits": sock,
            "max_socket_x": max([r["p95_x"] for r in sock], default=0.0),
            "max_any_x": max([r["p95_x"] for r in rows if r.get("p95_x")], default=0.0)}


# --------------------------------------------------------------------------- CPU family
def host_saturation_rule(cpu, rq):
    if not cpu["available"]:
        return {"fires": False, "why": "on-CPU attribution not in the pack"}
    fires = cpu["util_incident"] >= SATURATED
    return {"fires": fires, **_cpu_fields(cpu, rq),
            "why": (f"host CPU reached {cpu['util_incident']:.3f} of capacity with "
                    f"{cpu['thief_comm']} taking {cpu['thief_cores']} cores - no headroom left"
                    if fires else
                    f"host CPU at {cpu['util_incident']:.3f}, below the {SATURATED} ceiling")}


def cpu_throttle_rule(cpu, rq):
    if not cpu["available"]:
        return {"fires": False, "why": "on-CPU attribution not in the pack"}
    collapsed = cpu["util_ratio"] is not None and cpu["util_ratio"] <= COLLAPSE_RATIO
    no_thief = cpu["thief_cores"] < THIEF_CORES
    lost = cpu["loser_cores"] <= LOSER_CORES
    # MEASURED (finding F4): a slow datastore ALSO collapses host CPU - 0.433 -> 0.175 on
    # slow_db_aggressive_steady_r1 - so "the host went quiet" cannot separate the two. What
    # does is WHY it went quiet. Under a quota threads are runnable and held off the CPU, so
    # runqueue delay rises (measured 13.5-29.2x). Blocked on a datastore they are not
    # runnable at all, so it stays flat (1.59x). This is the "waiting more while working
    # less" clause the blueprint already states; it was missing from the code.
    waiting_for_cpu = (rq["max"] or 0) >= STARVED_RQ_X
    fires = collapsed and no_thief and lost and waiting_for_cpu
    return {"fires": fires, **_cpu_fields(cpu, rq),
            "why": (f"host CPU FELL to {cpu['util_ratio']:.2f} of its baseline "
                    f"({cpu['util_baseline']:.3f} -> {cpu['util_incident']:.3f}) with no new "
                    f"process, while threads waited {rq['max']}x longer - the system is doing "
                    f"less work, not competing for it"
                    if fires else
                    f"utilisation ratio {cpu['util_ratio']}, thief {cpu['thief_cores']} cores, "
                    f"biggest loss {cpu['loser_cores']}, runqueue {rq['max']}x - not a quota "
                    f"holding work back")}


def co_tenant_rule(cpu, rq, blk):
    if not cpu["available"]:
        return {"fires": False, "why": "on-CPU attribution not in the pack"}
    has_thief = cpu["thief_cores"] >= THIEF_CORES and not is_infra(cpu["thief_comm"])
    bounded = cpu["thief_cores"] < BIG_THIEF
    busy = cpu["util_incident"] >= CONTENDED
    headroom = cpu["util_incident"] < SATURATED
    rising = cpu["util_ratio"] is not None and cpu["util_ratio"] > 1.0
    fires = has_thief and bounded and busy and headroom and rising
    return {"fires": fires, **_cpu_fields(cpu, rq),
            "why": (f"{cpu['thief_comm']} took {cpu['thief_cores']} cores it was not using "
                    f"before, raising host CPU to {cpu['util_incident']:.3f} - busier, but "
                    f"still with headroom"
                    if fires else
                    f"thief {cpu['thief_comm']} {cpu['thief_cores']} cores, host "
                    f"{cpu['util_incident']} - does not match a bounded co-tenant workload")}


def _cpu_fields(cpu, rq):
    return {"host_util_baseline": cpu["util_baseline"],
            "host_util_incident": cpu["util_incident"],
            "host_util_ratio": cpu["util_ratio"],
            "thief_comm": cpu["thief_comm"], "thief_cores": cpu["thief_cores"],
            "biggest_loser_comm": cpu["loser_comm"], "biggest_loser_cores": cpu["loser_cores"],
            "corroboration_runqueue_max_x": rq["max"],
            "corroboration_runqueue_median_x": rq["median"]}


# ---------------------------------------------------------------------- datastore family
def datastore_rule(cpu, rq, blk, net):
    """One socket syscall inflates hugely while the component is not short of CPU, the path
    is not dropping packets, and something really is answering slowly.

    The first clause alone used to fire on hung dependencies (89x), degraded network paths
    (175x), memory caps and error storms, because socket blocking says a process is WAITING
    but not what it is waiting for. The two added clauses answer that from measurements the
    pack now carries.
    """
    top = blk["socket_hits"][0] if blk["socket_hits"] else None
    rq_ok = (rq["max"] or 0) < STARVED_RQ_X
    blocked = bool(top) and top["p95_x"] >= BLOCK_X

    # the path is losing packets -> a network fault, whatever else is true
    path_lossy = (net["retrans_available"]
                  and (net["worst_retrans_pct"] or 0) >= RETRANS_VETO_PCT)
    # something must actually be answering slowly, not merely be blocked
    answers_slowly = (not net["endpoint_available"]
                      or (net["worst_endpoint_x"] or 0) >= ENDPOINT_SLOWDOWN_MIN)

    fires = blocked and rq_ok and not path_lossy and answers_slowly
    comm = top["comm_syscall"].split("|")[0] if top else None
    call = top["comm_syscall"].split("|")[-1] if top else None
    if fires:
        why = (f"{comm} blocked in {call} for {top['p95_x']}x baseline, its endpoint answering "
               f"{net['worst_endpoint_x']}x slower, with runqueue delay flat at {rq['max']}x "
               f"and no packet loss on the path")
    elif path_lossy:
        why = (f"the path is retransmitting {net['worst_retrans_pct']}% of segments across "
               f"{net['n_impaired_ifaces']} interfaces - packets are being lost, so this is "
               f"the network rather than the datastore")
    elif blocked and rq_ok and not answers_slowly:
        why = (f"{comm} is blocked in {call} at {top['p95_x']}x, but the slowest endpoint is "
               f"only {net['worst_endpoint_x']}x - something is waiting, but nothing is "
               f"answering slowly enough for the datastore to be the cause")
    elif top:
        why = f"runqueue delay {rq['max']}x indicates CPU starvation, not dependency wait"
    else:
        why = "no socket-waiting syscall inflated enough"

    return {"fires": fires, "blocked_process": comm, "blocking_call": call,
            "blocking_x": top["p95_x"] if top else None,
            "max_runqueue_x": rq["max"],
            "worst_endpoint_x": net["worst_endpoint_x"],
            "worst_endpoint": net["worst_endpoint"],
            "worst_retrans_pct": net["worst_retrans_pct"],
            "checks_applied": {"retransmission": net["retrans_available"],
                               "endpoint_slowdown": net["endpoint_available"]},
            "converged_on": pack_converged(blk),
            "why": why}


def pack_converged(_blk):
    return None


COMM_TO_COMPONENT = {
    "sockshop":    {"mysqld": "catalogue-db", "mariadbd": "catalogue-db"},
    "trainticket": {"mysqld": "mysql", "mariadbd": "mysql"},
}


def comm_to_component(comm, app):
    return COMM_TO_COMPONENT.get(app, {}).get(comm, comm)


# The order here is only for reporting; every rule is evaluated on every incident.
VERDICTS = {
    "host-cpu-saturation":     ("host", "host_cpu_saturation", 0.85),
    "service-cpu-throttle":    (None,   "svc_cpu_cap",         0.80),
    "cpu-contention-co-tenant": ("host", "noisy_neighbor",     0.80),
    "datastore-wait":          (None,   "db_latency",          0.85),
}


def decide(pack):
    app = pack.get("app", "sockshop")
    cpu, rq, blk, net = _cpu(pack), _rq(pack), _blk(pack), _net(pack)

    results = {
        "host-cpu-saturation": host_saturation_rule(cpu, rq),
        "service-cpu-throttle": cpu_throttle_rule(cpu, rq),
        "cpu-contention-co-tenant": co_tenant_rule(cpu, rq, blk),
        "datastore-wait": datastore_rule(cpu, rq, blk, net),
    }
    fired = [n for n, r in results.items() if r["fires"]]

    verdict = {"run_id": pack.get("run_id"), "app": app,
               "blueprints_fired": fired,
               "oncpu_available": cpu["available"],
               "retrans_available": net["retrans_available"],
               "endpoint_available": net["endpoint_available"],
               "analysis_seconds": pack.get("total_analysis_s")}
    verdict.update({k.replace("-", "_"): v for k, v in results.items()})

    if len(fired) == 1:
        name = fired[0]
        svc, ftype, conf = VERDICTS[name]
        if name == "cpu-contention-co-tenant":
            svc = "host"
        elif name == "service-cpu-throttle":
            # MEASURED: the biggest loser is the busiest victim, not the capped service
            # (target carts/java lost 0.395 while front-end/node lost 0.876). We can say a
            # quota is throttling something; naming it needs cgroup-aware attribution.
            svc = None
        elif name == "datastore-wait":
            svc = comm_to_component(results[name]["blocked_process"], app)
        verdict.update(selected=name, root_cause_service=svc, fault_type=ftype,
                       confidence=conf, evidence=results[name]["why"])
    elif not fired and cpu["available"]:
        # "Nothing here matches" is now a real answer rather than a gap between rules.
        verdict.update(selected=None, root_cause_service=None, fault_type=None,
                       confidence=0.0,
                       evidence=("no blueprint matched. host CPU "
                                 f"{cpu['util_baseline']} -> {cpu['util_incident']} "
                                 f"(ratio {cpu['util_ratio']}), thief {cpu['thief_cores']} "
                                 f"cores, top socket wait {blk['max_socket_x']}x"))
    else:
        verdict.update(selected=None, root_cause_service=None, fault_type=None,
                       confidence=0.0,
                       evidence=(f"{len(fired)} blueprints fired: {', '.join(fired)}"
                                 if fired else "no blueprint matched and no on-CPU evidence"))
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    pack = json.load(open(a.pack, encoding="utf-8"))
    v = decide(pack)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(v, open(a.out, "w"), indent=2)
    print(f"{str(v['run_id']):44s} -> {str(v['selected']):26s} "
          f"{str(v['root_cause_service']):16s} {str(v['fault_type'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
