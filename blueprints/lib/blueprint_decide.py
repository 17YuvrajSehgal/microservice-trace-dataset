#!/usr/bin/env python3
"""Apply the two blueprints' decision rules to an L0 evidence pack. No model involved.

This is the blueprint arm of the comparison. It reads the SAME evidence pack every other
method gets, applies the rules written in the two blueprints, and returns a verdict in the
same shape the LLM methods return, so one scorer can grade them all.

Both blueprints are offered on every incident. Whichever fires is the answer; if both or
neither fire, that is recorded as ambiguous rather than being resolved by a coin flip. That
makes this a test of SELECTION as well as accuracy.

Thresholds come from the measured evidence, not from taste:
    blocking inflation >= 5x     (measured 36.8x on the datastore fault, 1.12x control)
    runqueue inflation >= 2x     (measured 7.12x on the CPU fault, 0.97x control)

    python3 blueprint_decide.py --pack <pack.json> [--out verdict.json]
"""
from __future__ import annotations
import argparse, json, os, sys

BLOCK_X = 5.0
RQ_X = 2.0
SOCKET_CALLS = ("poll", "epoll_wait", "epoll_pwait", "recvfrom", "recvmsg", "read", "select")
# processes that are not application components; never name one as the culprit
INFRA = ("kworker", "ksoftirqd", "rcu_", "kswapd", "kcompactd", "migration", "watchdog",
         "systemd", "containerd", "dockerd", "cadvisor", "prometheus", "node_export",
         "google_guest", "runc", "sshd", "irq/")


def is_infra(name):
    n = (name or "").lower()
    return any(k in n for k in INFRA)


def cpu_rule(pack):
    """CPU contention: runqueue delay inflates broadly, syscall durations stay flat."""
    rq = pack["runqueue_delay"]["top_by_inflation"]
    blk = pack["blocking_syscall"]["top_by_inflation"]
    xs = [r["p95_x"] for r in rq if r.get("p95_x")]
    if not xs:
        return {"fires": False, "why": "no runqueue measurements available"}
    top = max(xs)
    median = sorted(xs)[len(xs) // 2]
    n_inflated = sum(1 for x in xs if x >= RQ_X)
    # MEASURED REFINEMENT: under CPU starvation *every* syscall lengthens a little, because
    # the thread is descheduled inside it. connect() reached 5.3x on two co-tenant runs and
    # wrongly vetoed this rule. The datastore signature is specifically a socket-WAITING call
    # inflating hugely, so the veto must use that same set. Across all five co-tenant runs the
    # max socket-wait inflation is 1.5-2.99x, against 36.8x on the datastore fault.
    sock = [r["p95_x"] for r in blk
            if r.get("p95_x") and r["comm_syscall"].split("|")[-1] in SOCKET_CALLS]
    max_blk = max(sock or [0])
    max_any = max([r["p95_x"] for r in blk if r.get("p95_x")] or [0])

    fires = top >= RQ_X and n_inflated >= 3 and max_blk < BLOCK_X
    # the culprit is the workload that took the CPU, which the call graph does not contain.
    # From L0 alone we can name the most-delayed application process; the container-level
    # attribution comes from the metrics step of the blueprint.
    worst_app = next((r["service"] for r in rq
                      if r.get("p95_x", 0) >= RQ_X and not is_infra(r["service"])), None)
    return {
        "fires": fires,
        "max_runqueue_x": top, "median_runqueue_x": median,
        "n_processes_inflated": n_inflated,
        "max_socket_wait_x": max_blk, "max_any_syscall_x": max_any,
        "most_delayed_app_process": worst_app,
        "why": (f"runqueue delay up to {top}x across {n_inflated} processes "
                f"(median {median}x) while no socket-waiting syscall inflated past {max_blk}x"
                if fires else
                f"runqueue top {top}x over {n_inflated} processes, max socket-wait {max_blk}x "
                f"- does not match broad CPU starvation"),
    }


def db_rule(pack):
    """Datastore wait: one socket syscall inflates hugely, runqueue delay stays flat."""
    rq = pack["runqueue_delay"]["top_by_inflation"]
    blk = pack["blocking_syscall"]["top_by_inflation"]
    xs = [r["p95_x"] for r in rq if r.get("p95_x")]
    rq_max = max(xs) if xs else 0.0

    hits = [r for r in blk
            if r.get("p95_x", 0) >= BLOCK_X
            and r["comm_syscall"].split("|")[-1] in SOCKET_CALLS
            and not is_infra(r["comm_syscall"].split("|")[0])]
    hits.sort(key=lambda r: -r["p95_x"])
    top = hits[0] if hits else None

    fires = bool(top) and rq_max < RQ_X
    comm = top["comm_syscall"].split("|")[0] if top else None
    call = top["comm_syscall"].split("|")[-1] if top else None
    return {
        "fires": fires,
        "blocked_process": comm, "blocking_call": call,
        "blocking_x": top["p95_x"] if top else None,
        "max_runqueue_x": rq_max,
        "converged_on": pack["call_graph"].get("converged_on"),
        "why": (f"{comm} blocked in {call} for {top['p95_x']}x baseline while runqueue delay "
                f"stayed at {rq_max}x"
                if fires else
                (f"runqueue delay {rq_max}x indicates CPU starvation, not dependency wait"
                 if top else "no socket-waiting syscall inflated enough")),
    }


# Process name -> the component name the ground truth uses. This is per-application: the
# same `mysqld` process is the per-service datastore on one app and the single shared
# datastore on the other, so the mapping cannot be global.
COMM_TO_COMPONENT = {
    "sockshop":    {"mysqld": "catalogue-db", "mariadbd": "catalogue-db"},
    "trainticket": {"mysqld": "mysql", "mariadbd": "mysql"},
}


def comm_to_component(comm, app):
    return COMM_TO_COMPONENT.get(app, {}).get(comm, comm)


def decide(pack):
    cpu, db = cpu_rule(pack), db_rule(pack)
    fired = [n for n, r in (("cpu-contention", cpu), ("datastore-wait", db)) if r["fires"]]

    verdict = {"run_id": pack["run_id"], "app": pack["app"],
               "blueprints_fired": fired,
               "cpu_contention": cpu, "datastore_wait": db,
               "analysis_seconds": pack.get("total_analysis_s")}

    if len(fired) == 1 and fired[0] == "cpu-contention":
        verdict.update(selected="cpu-contention",
                       root_cause_service="host",
                       fault_type="noisy_neighbor",
                       confidence=0.8,
                       evidence=cpu["why"])
    elif len(fired) == 1:
        comm = db["blocked_process"]
        verdict.update(selected="datastore-wait",
                       root_cause_service=comm_to_component(comm, pack.get("app", "sockshop")),
                       fault_type="db_latency",
                       confidence=0.85,
                       evidence=db["why"])
    else:
        verdict.update(selected=None, root_cause_service=None, fault_type=None,
                       confidence=0.0,
                       evidence=("both blueprints fired" if len(fired) == 2
                                 else "neither blueprint fired") +
                                f" | cpu: {cpu['why']} | datastore: {db['why']}")
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
    print(f"{v['run_id']:44s} -> {str(v['selected']):16s} "
          f"{str(v['root_cause_service']):16s} {str(v['fault_type'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
