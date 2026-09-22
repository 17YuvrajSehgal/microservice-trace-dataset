#!/usr/bin/env python3
"""Re-mark the WHAT axis for every run at once, with a tighter rubric.

WHY A SEPARATE PASS
-------------------
`what_score` is computed per cell as it runs, so changing the rubric mid-matrix would leave
early cells marked one way and late cells another, and the arms would no longer be comparable.
The rubric turned out to be too loose the moment real answers arrived - `slow_db` scored 98%,
because its keyword list contained bare "db", which matches "catalogue-db" in literally any
answer that names the container. So: leave the run alone, and re-mark all 360 afterwards with
one rubric.

Nothing here reads a transcript or re-runs a model. It reads the words the agent already
wrote, so it is cheap and repeatable, and the original score.json is never modified - the
rescored value is written next to it.

WHAT CHANGED FROM v1
--------------------
Bare generic tokens are gone. "db", "cpu", "wait", "only", "limit" and the like fire on almost
any sentence about a trace and so measure nothing. v2 asks for phrases that only appear if the
agent actually said the thing: not "cpu" but "cpu contention" or "competing for cpu"; not "db"
but "database" or "datastore".

A miss still means "go and read the run", not "the run is wrong". The review sheet is the
authority; this only sorts 360 answers so a human does not have to start from scratch.

    python q2_rescore.py --out-dir /scratch/yuvraj17/stratatrace/results/q2-full
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RUBRIC_VERSION = 2

# Each concept: (what it means, [phrases, any one of which counts]).
# Phrases, not tokens. A token like "cpu" appears in every answer about a kernel trace.
CONCEPTS = {
    "noisy_neighbor": [
        ("an extra workload that is not part of the application", [
            "co-tenant", "cotenant", "noisy neighbour", "noisy neighbor", "stress-ng",
            "stress ng", "foreign process", "external process", "unrelated workload",
            "background job", "not part of the app", "not one of the application",
            "off-call-path", "off call path", "new process", "extra process",
            "newly appear", "newcomer", "appears only", "did not exist before",
            "absent in the baseline", "absent from the earlier",
        ]),
        ("it is taking CPU away from the others", [
            "cpu contention", "competing for cpu", "compete for cpu", "contend for cpu",
            "cpu competition", "scheduler contention", "runqueue", "run queue",
            "starved of cpu", "cpu starvation", "preempt", "stealing cpu", "takes cpu",
            "taking cpu", "consumes cpu", "consuming cpu", "on-cpu time", "cpu share",
        ]),
        ("the application services are victims, not the cause", [
            "victim", "not the cause", "rather than the cause", "no single service",
            "headroom", "not saturated", "not exhausted", "spare capacity",
            "still succeed", "keep working", "keeps working", "still working",
            "still running normally", "remain healthy", "unaffected", "collateral",
            "no component is itself", "not itself busy", "not itself saturated",
        ]),
    ],
    "anomaly_cpu": [
        ("the host CPU is exhausted, not merely busy", [
            "cpu saturat", "cpu exhaust", "fully saturated", "at the ceiling",
            "no headroom", "pinned at", "100% cpu", "cpu is maxed", "maxed out",
            "run out of cpu", "cpu starvation",
        ]),
        ("everything degrades together", [
            "all services", "across the board", "host-wide", "system-wide",
            "every service", "many services", "everything slow", "broad impact",
            "not one service", "no single service",
        ]),
        ("an extra workload is responsible", [
            "stress-ng", "stress ng", "extra workload", "new process", "appears only",
            "absent in the baseline", "additional load", "injected load",
        ]),
    ],
    "slow_db": [
        ("a datastore is answering slowly", [
            "database", "datastore", "mysql", "sql query", "db query", "query latency",
            "slow database", "database latency", "db latency",
        ]),
        ("the callers are waiting on it rather than being busy themselves", [
            "waiting on", "blocked on", "blocking wait", "dependency wait",
            "external wait", "downstream", "not cpu-bound", "not cpu bound",
            "not itself busy", "idle while waiting", "recvfrom", "epoll_wait",
            "socket wait", "waiting for a response",
        ]),
        ("the delay is added to the path, not caused by the datastore working harder", [
            "added latency", "injected latency", "induced latency", "proxy",
            "toxiproxy", "not saturated", "no cpu pressure", "no disk pressure",
            "without saturation", "artificial delay", "network delay on the path",
        ]),
    ],
    "anomaly_net": [
        ("the network path is degraded", [
            "packet loss", "network latency", "network delay", "retransmi", "rtt",
            "dropped packet", "net_dev", "netif_receive", "network path",
            "degraded network",
        ]),
        ("it affects traffic broadly, not one component", [
            "host-wide", "all services", "across the board", "every service",
            "many services", "not one service", "no single service", "system-wide",
        ]),
        ("the hosts and services themselves look healthy", [
            "not cpu", "no cpu pressure", "not saturated", "headroom", "not exhausted",
            "no disk", "services look healthy", "no single culprit",
        ]),
    ],
    "svc_net": [
        ("one service's network path is degraded", [
            "packet loss", "network latency", "network delay", "retransmi",
            "net_dev", "netif_receive", "socket", "network path",
        ]),
        ("only that one service is affected", [
            "one service", "single service", "only this", "only that", "isolated to",
            "specific container", "that container", "confined to", "limited to",
        ]),
        ("the host network is fine", [
            "host network is", "host is fine", "host looks healthy", "not host-wide",
            "no host-level", "other services are unaffected", "rest of the system",
        ]),
    ],
    "svc_cpu_cap": [
        ("one service is held back by its own CPU limit", [
            "throttl", "cfs quota", "cpu quota", "cpu cap", "cpu limit", "cgroup limit",
            "hit its limit", "capped at",
        ]),
        ("it is not the host running out of CPU", [
            "host is fine", "host looks healthy", "host has headroom", "not host-wide",
            "no host-level", "host is not saturated", "plenty of cpu on the host",
        ]),
        ("only that service slows", [
            "one service", "single service", "only this", "only that", "isolated to",
            "that container", "confined to", "limited to", "other services are",
        ]),
    ],
}


# The best WHERE answer each fault ALLOWS. Not every fault has a process to name.
#
# `anomaly_net` is netem applied to the host's own interface: there is no container, no extra
# process, nothing to point at but the host. So "host" is the correct and complete answer
# there, and counting it as a partial one would mark a right answer wrong. Measured on the
# first 60 runs of it: named=0 for every single run, which is not the agent failing - it is
# structurally impossible.
#
# The others all have something nameable: a stress-ng container, a database, or the one
# container whose veth was degraded. For those, "host" really is a hedge.
WHERE_CEILING = {
    "anomaly_net": "scope",      # netem on the host itself - nothing to name
    "noisy_neighbor": "named",   # the stress-ng co-tenant container
    "anomaly_cpu": "named",      # the stress-ng container
    "slow_db": "named",          # catalogue-db / mysqld
    "svc_net": "named",          # netem on ONE container's veth
    "svc_cpu_cap": "named",      # one container's cgroup quota
}


def where_ok(where: str, problem: str) -> bool:
    """Did it get WHERE right, judged against the best answer this fault allows?"""
    ceiling = WHERE_CEILING.get(problem, "named")
    if ceiling == "scope":
        return where in ("named", "scope")
    return where == "named"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower())


def score_what_v2(text: str, problem: str) -> dict:
    cs = CONCEPTS.get(problem) or []
    if not cs:
        return {"what_score_v2": None, "hit": [], "missed": [], "n_concepts": 0}
    t = _norm(text)
    hit, missed = [], []
    for name, phrases in cs:
        (hit if any(_norm(p) in t for p in phrases) else missed).append(name)
    return {"what_score_v2": round(len(hit) / len(cs), 3),
            "hit": hit, "missed": missed, "n_concepts": len(cs)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/scratch/yuvraj17/stratatrace/results/q2-full")
    ap.add_argument("--write", action="store_true",
                    help="write rescored.json next to each score.json (default: report only)")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.out_dir, "*", "*", "*", "*", "*", "score.json")))
    if not paths:
        print("no score.json under %s" % a.out_dir)
        return 1

    rows = []
    for sp in paths:
        try:
            r = json.load(open(sp, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cell = os.path.dirname(sp)
        d = {}
        dp = os.path.join(cell, "diagnosis.json")
        if os.path.exists(dp):
            try:
                d = json.load(open(dp, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        text = "%s %s" % (d.get("what_is_wrong", "") or r.get("what_is_wrong", "") or "",
                          d.get("evidence", "") or "")
        v2 = score_what_v2(text, r.get("problem", ""))
        r["_v2"] = v2
        r["_cell"] = cell
        rows.append(r)
        if a.write:
            out = {"rubric_version": RUBRIC_VERSION, **v2}
            json.dump(out, open(os.path.join(cell, "rescored.json"), "w"), indent=1)

    print("rescored %d runs with rubric v%d\n" % (len(rows), RUBRIC_VERSION))

    by = defaultdict(list)
    for r in rows:
        by[r.get("problem", "?")].append(r)

    print("%-16s %4s %8s   %8s %8s   %s"
          % ("problem", "n", "WHERE ok", "what v1", "what v2", "concept most often missed"))
    print("-" * 104)
    for prob in sorted(by):
        rs = by[prob]
        v1 = [r["what_score"] for r in rs if isinstance(r.get("what_score"), (int, float))]
        v2 = [r["_v2"]["what_score_v2"] for r in rs
              if isinstance(r["_v2"].get("what_score_v2"), (int, float))]
        ok = sum(1 for r in rs if where_ok(r.get("where", ""), prob))
        miss = Counter()
        for r in rs:
            for m in r["_v2"]["missed"]:
                miss[m] += 1
        top = miss.most_common(1)
        print("%-16s %4d %4d/%-3d   %7s%% %7s%%   %s"
              % (prob, len(rs), ok, len(rs),
                 "%.0f" % (100 * sum(v1) / len(v1)) if v1 else " -",
                 "%.0f" % (100 * sum(v2) / len(v2)) if v2 else " -",
                 ("%s (%d)" % (top[0][0], top[0][1])) if top else ""))
    print()
    print("WHERE ok is judged against the best answer each fault allows: for anomaly_net the")
    print("netem sits on the host's own interface, so 'host' IS the complete answer and there")
    print("is nothing to name. Everywhere else 'host' is a hedge.")

    print()
    print("%-16s %-14s %8s %8s" % ("problem", "ask | arm", "v2", "n"))
    print("-" * 52)
    for prob in sorted(by):
        for ask in ("nohint", "hint"):
            for arm in ("none", "given"):
                rs = [r for r in by[prob] if r.get("ask") == ask and r.get("arm") == arm]
                if not rs:
                    continue
                v2 = [r["_v2"]["what_score_v2"] for r in rs
                      if isinstance(r["_v2"].get("what_score_v2"), (int, float))]
                print("%-16s %-14s %7s%% %8d"
                      % (prob, "%s|%s" % (ask, arm),
                         "%.0f" % (100 * sum(v2) / len(v2)) if v2 else " -", len(rs)))
    if not a.write:
        print()
        print("(report only - pass --write to save rescored.json next to each score.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
