#!/usr/bin/env python3
"""A fairer way to mark the agent's answer.

WHY THE OLD MARKING WAS UNFAIR
------------------------------
Two problems, both found in the 60-run pilot.

1. It required an exact label. The agent had to pick `noisy_neighbor` from a fixed list. But
   the list was written for a four-modality view, and from a kernel trace alone several of its
   entries are not separable. An agent that said "a foreign process is eating CPU while the
   services keep working" understood the incident perfectly and scored zero for calling it
   `cpu_saturation`. We are marking vocabulary, not analysis.

2. It merged two different answers about WHERE. `_svc_match` accepts both `host` and
   `stress-ng*` for a host-scoped fault. One is a safe guess that is right by default; the
   other is actually finding the process. Merged, the column moved 47% -> 13% between arms
   while the real find rate sat flat at 3/2/2/2.

WHAT THIS SCORES INSTEAD
------------------------
Three separate things, none of which needs the agent to guess a label:

  WHERE   named the injected process | right scope only | wrong        (three-way, not binary)
  WHAT    how much of the mechanism its own description covers          (concepts, any synonym)
  HOW     which tools it used to get there, and whether it checked WHO  (objective, from the log)

WHEN stays as it was - overlap with the true window.

None of this replaces reading the answers. It sorts 60 runs so a human can scan them, and
q2_review.py prints them for exactly that. Concept matching is deliberately generous: it is
there to catch "did it say the thing at all", and a miss should be read as "go and look",
not as a verdict.
"""
from __future__ import annotations

import re

# Per problem: what counts as naming the culprit, what scope-level answers are acceptable, and
# the ideas a correct description contains. Synonyms are generous on purpose - the agent is
# writing free text and should not be penalised for wording.
#
# `culprit` is the injected thing as the KERNEL sees it. Kernel process names are cut to 15
# characters, so these are matched as substrings both ways.
RUBRIC = {
    "noisy_neighbor": {
        "culprit": ["stress-ng", "stress"],
        "scope": ["host", "node", "machine"],
        "scope_is_defensible": True,   # the fault IS host-scoped; "host" is a real answer
        "concepts": [
            ("a workload that is not part of the application",
             ["co-tenant", "cotenant", "noisy neighbour", "noisy neighbor", "stress",
              "foreign", "external process", "unrelated workload", "background job",
              "not part of the app", "off-call-path", "off call path", "newcomer",
              "new process", "extra process", "another process", "third-party"]),
            ("competing for CPU",
             ["cpu", "on-cpu", "scheduler", "sched", "runqueue", "run queue", "contention",
              "contend", "competing", "starv", "preempt", "time slice", "core"]),
            ("the application services are victims, not the cause",
             ["victim", "not itself", "no single service", "services still", "headroom",
              "not saturated", "not exhausted", "spare capacity", "still succeed",
              "keep working", "keeps working", "still working", "still running",
              "mild", "unaffected", "remain healthy", "no component is", "not the cause",
              "rather than the cause", "collateral", "affected by", "suffering"]),
        ],
    },
    # Drafts for the other five. Written from fault_catalog.md, NOT yet checked against real
    # answers - the pilot has only run noisy_neighbor. Revisit each before its problem runs.
    "anomaly_cpu": {
        "culprit": ["stress-ng", "stress"], "scope": ["host", "node", "machine"],
        "scope_is_defensible": True,
        "concepts": [
            ("host CPU is exhausted", ["cpu", "saturat", "exhaust", "ceiling", "100%",
                                       "no headroom", "pinned", "fully busy"]),
            ("everything slows together", ["all services", "across the board", "everywhere",
                                           "host-wide", "system-wide", "every service",
                                           "many services"]),
        ],
    },
    "slow_db": {
        "culprit": ["mysql", "mysqld", "catalogue-db", "carts-db", "toxiproxy"],
        "scope": ["database", "datastore", "db"], "scope_is_defensible": True,
        "concepts": [
            ("a datastore answers slowly", ["database", "db", "datastore", "mysql", "query",
                                            "sql"]),
            ("callers wait on it rather than being busy themselves",
             ["wait", "blocked", "blocking", "idle", "not busy", "external", "downstream",
              "dependency", "caller"]),
        ],
    },
    "anomaly_net": {
        "culprit": [], "scope": ["host", "node", "network", "machine"],
        "scope_is_defensible": True,
        "concepts": [
            ("the network path is degraded", ["network", "packet", "latency", "delay", "loss",
                                              "retransmit", "rtt", "net_dev", "socket"]),
            ("it affects traffic broadly, not one component",
             ["host-wide", "all services", "everywhere", "across", "many services",
              "not one service", "no single"]),
        ],
    },
    "svc_net": {
        "culprit": [], "scope": [], "scope_is_defensible": False,
        "concepts": [
            ("one service's network path is degraded",
             ["network", "packet", "latency", "delay", "loss", "socket", "net_dev"]),
            ("only traffic through that one service is affected",
             ["one service", "single service", "only", "specific", "isolated",
              "that container"]),
        ],
    },
    "svc_cpu_cap": {
        "culprit": [], "scope": [], "scope_is_defensible": False,
        "concepts": [
            ("one service is held back by its own CPU limit",
             ["throttl", "quota", "cap", "limit", "cgroup", "cfs"]),
            ("the host itself is fine", ["host is", "host fine", "host healthy", "headroom",
                                         "not host", "host-level", "no host"]),
        ],
    },
}

# The two tools that answer WHO rather than HOW MUCH. Whether the agent reached for them is
# the most interesting thing in its trajectory, because the pilot's failure was searching only
# on volume.
WHO_TOOLS = ("ctf_procdiff", "ctf_proclife")


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower())


# Process names a kernel trace shows for MANY different services. Sock Shop runs several Java
# containers, so `java` in a sched_switch line could be any of them; the same goes for node and
# python3, and for the container runtime itself. An agent that answers one of these has found a
# real signal and has NOT localised it. Scoring that as simply "wrong" hides the distinction,
# and scoring it right would be generous to the point of meaningless - so it gets its own
# bucket. It is also a result in its own right: from a kernel trace alone, a per-service fault
# in a Java stack may not be separable at all.
AMBIGUOUS_RUNTIME = ("java", "node", "python3", "python", "dockerd", "containerd-shim",
                     "containerd", "runc", "docker-proxy")

# A Linux namespace inode: 10 digits starting 402. Containers on this host sit in the
# 4026532000-4026534000 range.
_NS_RE = re.compile(r"\b402[0-9]{7}\b")


def score_where(pred_service: str, kind: str, problem: str,
                true_service: str = "", scope: str = "", true_ns: str = "") -> dict:
    """Four ways, because 'host', 'java' and 'stress-ng-cpu' are three different answers.

    named      - identified the injected thing
    scope      - right level, not the thing. Only for a host-scoped fault, where 'host' is a
                 real answer, just a less useful one
    ambiguous  - a shared runtime process that maps to several services
    wrong      - anything else

    `true_service` comes from the run's own ground truth, so the accept set does not depend on
    me having guessed the right names per problem in advance. Ground truth belongs here, in the
    scorer - never in a tool the agent can reach.
    """
    r = RUBRIC.get(problem) or {}
    p = _norm(pred_service).strip()
    if not p:
        return {"where": "none", "pred": pred_service, "kind": kind}

    host_scoped = (_norm(true_service).strip() == "host") or (_norm(scope).strip() == "host")

    # the injected thing, per the rubric AND per this run's own ground truth
    accept = list(r.get("culprit", []))
    if true_service and not host_scoped:
        accept.append(true_service)
    for c in accept:
        cn = _norm(c).strip()
        if not cn:
            continue
        if cn in p or p in cn:
            return {"where": "named", "pred": pred_service, "kind": kind, "matched": c}

    if host_scoped:
        for sc in list(r.get("scope", [])) + ["host"]:
            if p == sc or p.startswith(sc):
                return {"where": "scope", "pred": pred_service, "kind": kind, "matched": sc}

    # Did it narrow to ONE container? The kernel records no service name - only a pid_ns per
    # container - so "java in pid_ns 4026533460" is the most precise answer the trace allows.
    # It is not the same as saying "carts", and it is not the same as saying "host" either: it
    # picks one container out of the 21 on this machine. It gets its own outcome so the
    # improvement is visible instead of being filed as `ambiguous` or `wrong`.
    if _NS_RE.search(str(pred_service or "")):
        # NAMING A CONTAINER IS NOT THE SAME AS NAMING THE RIGHT ONE. This branch used to
        # credit any pid_ns at all, which was harmless while no blueprint asked the agent to
        # pick one, and stops being harmless the moment one does - "rank the containers and
        # name the lowest" would score right whether the ranking worked or not.
        #
        # `true_ns` comes from nsmap, which matches a container to a namespace by CPU time and
        # REFUSES when the match is ambiguous. So there are three outcomes, not two, and the
        # third is the honest one: on Train Ticket 27 of 41 containers sit within 15% of each
        # other on CPU, so for most of them we cannot say which namespace they are.
        got = _NS_RE.search(str(pred_service)).group(0)
        out = {"where": "container", "pred": pred_service, "kind": kind, "pid_ns": got}
        if true_ns:
            out["container_correct"] = (got == true_ns)
            out["true_pid_ns"] = true_ns
            if got != true_ns:
                out["where"] = "container_wrong"
        else:
            out["container_correct"] = None      # unresolvable, not a pass
            out["where"] = "container_unverified"
        return out

    for amb in AMBIGUOUS_RUNTIME:
        if p == amb or p.startswith(amb):
            return {"where": "ambiguous", "pred": pred_service, "kind": kind, "matched": amb}

    return {"where": "wrong", "pred": pred_service, "kind": kind}


def score_what(text: str, problem: str) -> dict:
    """How much of the mechanism the agent's own words cover.

    Any synonym counts. This is a coverage check, not a grade: it answers "did it mention
    this at all", so a low score means go and read the answer, not that the answer is wrong.
    """
    r = RUBRIC.get(problem) or {}
    concepts = r.get("concepts") or []
    if not concepts:
        return {"what_score": None, "hit": [], "missed": [], "n_concepts": 0}
    t = _norm(text)
    hit, missed = [], []
    for name, words in concepts:
        (hit if any(_norm(w) in t for w in words) else missed).append(name)
    return {"what_score": round(len(hit) / len(concepts), 3),
            "hit": hit, "missed": missed, "n_concepts": len(concepts)}


def score_how(trajectory) -> dict:
    """What the agent actually did. Objective, straight from the tool log.

    used_who_tools is the one to watch: the pilot's systematic error was searching only for a
    change in event volume, so whether an agent reached for the presence tools at all - and
    whether that goes with getting the window right - is the question the new tools exist to
    answer.
    """
    names = [t.get("tool") for t in (trajectory or []) if t.get("tool")]
    seq = [n for n in names if n != "submit_diagnosis"]
    return {
        "n_tool_calls": len(seq),
        "distinct_tools": sorted(set(seq)),
        "used_who_tools": any(n in WHO_TOOLS for n in seq),
        "n_who_calls": sum(1 for n in seq if n in WHO_TOOLS),
        "used_raw_lines": "ctf_lines" in seq,
        "tool_sequence": seq,
    }


def judge(diagnosis: dict, trajectory, problem: str,
          true_service: str = "", scope: str = "", true_ns: str = "") -> dict:
    """All three axes for one run."""
    d = diagnosis or {}
    where = score_where(d.get("root_cause_service", ""), d.get("culprit_kind", ""), problem,
                        true_service=true_service, scope=scope, true_ns=true_ns)
    # Both fields, because the mechanism often lands in the evidence rather than the summary,
    # and marking it absent on a wording split would be exactly the unfairness this replaces.
    what = score_what("%s %s" % (d.get("what_is_wrong", ""), d.get("evidence", "")), problem)
    how = score_how(trajectory)
    return {"where": where, "what": what, "how": how}
