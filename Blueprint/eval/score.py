#!/usr/bin/env python3
"""Score ONE agent verdict against a run's ground truth: did it detect the fault, name the
right place, and find the window.

Reads ground truth HERE, in the scorer, never anywhere a tool the agent can reach. Two dataset
shapes, deliberately handled apart because their notion of "where" differs:

  microservice  run_dir/ground_truth.json -> fault.{name,scope,target_service,parameters}
                the fault is localised to a named service/container; WHERE is scorable.
  agentic       run_dir/meta/ground_truth.json -> {cpu_max, mem_limit, io_max, ...}
                the cap is on the whole run's cgroup (the agent's own process); there is no
                "victim service" to name, so WHERE is the run's own workload, and the real
                question is whether the fault TYPE and PRESENCE were called correctly.

A run can be a CONTROL (uncapped baseline). Detecting a control = saying "normal / no fault".
"""
from __future__ import annotations
import json
import os
import re

import nsmap

# fault family -> the words an agent's fault_type may use for it. Matched case-insensitively as
# substrings, so "cpu_cap", "CFS throttle", "cpu throttling" all count for svc_cpu_cap.
FAULT_WORDS = {
    "svc_cpu_cap":   ("cpu", "throttl", "quota", "cfs", "cap"),
    "svc_mem_cap":   ("mem", "reclaim", "oom", "cap", "cgroup"),
    "noisy_neighbor": ("cpu", "contention", "co-tenant", "cotenant", "noisy", "steal", "satur"),
    "slow_db":       ("db", "database", "datastore", "dependency", "query", "connection"),
    "svc_net":       ("net", "network", "packet", "latency", "retransm", "loss", "delay"),
    "io_cap":        ("io", "disk", "block", "writeback", "throttl"),
    "threads":       ("cpu", "runqueue", "run-queue", "wait", "contention", "schedul"),
}

# a verdict's fault_type that means "nothing wrong" - used to score control/baseline runs
NORMAL_WORDS = ("normal", "no fault", "no incident", "healthy", "nothing", "no anomaly",
                "no issue", "baseline", "not a fault", "no cap", "uncapped")


def _conclusion(dx: dict) -> str:
    """The agent's CONCLUSION only - fault_type and the one-line what_is_wrong - lowercased.
    NOT the evidence: evidence on a clean run naturally says "checked CPU, found nothing", and
    matching fault words there made every control look like a false positive. The verdict is
    the fault_type the agent committed to, not the ground it walked to get there."""
    d = dx or {}
    return (str(d.get("fault_type", "")) + " " + str(d.get("what_is_wrong", ""))).lower()


# --------------------------------------------------------------------------------------
# ground truth adapters
# --------------------------------------------------------------------------------------
def load_truth(run_dir: str) -> dict:
    """Normalise either dataset's ground truth to {family, present, scope, target, container,
    window:(begin,end)|None, raw}. `present` is False for an uncapped/baseline control."""
    ms = os.path.join(run_dir, "ground_truth.json")
    ag = os.path.join(run_dir, "meta", "ground_truth.json")
    if os.path.exists(ms):
        return _truth_microservice(json.load(open(ms, encoding="utf-8")))
    if os.path.exists(ag):
        return _truth_agentic(json.load(open(ag, encoding="utf-8")))
    return {"family": None, "present": None, "scope": "", "target": "", "container": "",
            "window": None, "raw": {}}


def _truth_microservice(gt: dict) -> dict:
    f = gt.get("fault") or gt
    name = (f.get("name") or "").lower()
    # the family is the recipe name with any target suffix dropped (svc_cpu_cap_carts -> svc_cpu_cap)
    fam = None
    for k in FAULT_WORDS:
        if name.startswith(k):
            fam = k
            break
    b = (f.get("injection_start_utc") or "").split("T")[-1].rstrip("Z") or None
    e = (f.get("injection_end_utc") or "").split("T")[-1].rstrip("Z") or None
    return {"family": fam, "present": True, "scope": (f.get("scope") or "").lower(),
            "target": (f.get("target_service") or "").lower(),
            "container": ((f.get("parameters") or {}).get("container") or ""),
            "window": (b, e) if b and e else None, "raw": gt}


def _truth_agentic(gt: dict) -> dict:
    """Agentic caps: fault present when a limit is set to something other than unlimited."""
    cpu = str(gt.get("cpu_max") or "").strip()
    mem = str(gt.get("mem_limit") or "").strip()
    io = str(gt.get("io_max") or "").strip()
    fam, present = None, False
    if mem and mem.lower() not in ("", "max", "none", "nocap"):
        fam, present = "svc_mem_cap", True
    elif cpu and cpu.lower() not in ("", "max", "none", "nocap"):
        fam, present = "svc_cpu_cap", True
    elif io and io.lower() not in ("", "max", "none", "nocap"):
        fam, present = "io_cap", True
    else:
        # no limit set -> a baseline/control. Family is whichever experiment it belongs to,
        # inferred from which knob EXISTS at all (even if "max"); used only to pick the blueprint.
        if mem:
            fam = "svc_mem_cap"
        elif io:
            fam = "io_cap"
        else:
            fam = "svc_cpu_cap"
        present = False
    return {"family": fam, "present": present, "scope": "cgroup",
            "target": (gt.get("task") or gt.get("run") or "").lower(), "container": "",
            "window": None, "raw": gt}


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------
def _fault_match(verdict_text: str, family: str) -> bool:
    words = FAULT_WORDS.get(family, ())
    return any(w in verdict_text for w in words)


def _says_normal(verdict_text: str) -> bool:
    return any(w in verdict_text for w in NORMAL_WORDS)


def _where_microservice(dx: dict, truth: dict, run_dir: str, index_root=None) -> str:
    """named | container | scope | wrong | none - how well the agent localised a microservice
    fault, reusing the study's rule: a service name, or a pid_ns that maps to the right
    container, or the right scope (host), counts."""
    pred = (dx.get("root_cause_service") or "").strip()
    if not pred:
        return "none"
    low = pred.lower()
    target = truth["target"]
    if target and target in re.split(r"[^a-z0-9]+", low):
        return "named"
    # a pid_ns id -> resolve it to a container and compare to the true one
    m = re.search(r"\b(40265\d{5}|\d{6,})\b", pred)
    if m and target:
        try:
            true_ns = nsmap.ns_for_service(run_dir, target, index_root=index_root)
        except Exception:                                               # noqa: BLE001
            true_ns = None
        if true_ns and m.group(1) == str(true_ns):
            return "container"
    if truth["scope"] == "host" and ("host" in low or "whole" in low or "every" in low):
        return "scope"
    return "wrong"


def score(dx: dict, run_dir: str, family: str, index_root=None) -> dict:
    """Grade one verdict. Returns the row the matrix aggregates.

    detected: the headline. For a real fault = right fault type (and, microservice, the right
    place). For a control = the agent said normal/no-fault.
    """
    truth = load_truth(run_dir)
    fam = family or truth["family"]
    agentic = truth["scope"] == "cgroup"

    # Judge from the fault_type the agent committed to. A fault_type that is empty or names a
    # normal/no-fault outcome is "said normal"; otherwise it is a real fault claim only when it
    # carries this family's words.
    ft = (dx.get("fault_type") or "").strip().lower()
    concl = _conclusion(dx)
    said_normal = (not ft) or _says_normal(ft)
    fault_ok = (not said_normal) and _fault_match(ft or concl, fam)

    if truth["present"] is False:
        # control/baseline: correct = the agent did NOT claim this fault
        detected = said_normal or not fault_ok
        return {"detected": bool(detected), "control": True, "present": False,
                "fault_ok": fault_ok, "said_normal": said_normal, "where": "n/a",
                "window_iou": None, "family": fam, "agentic": agentic}

    where = "n/a" if agentic else _where_microservice(dx, truth, run_dir, index_root)
    # A host-scope fault (noisy_neighbor) has no single victim service to name - the correct
    # localisation is identifying the aggressor or saying "host-wide", and the recipe's own
    # ground truth says target_service="host". So for host scope, do not gate detection on
    # pinning a victim; the fault type carries it, same as the agentic (own-cgroup) case.
    where_ok = (where in ("named", "container", "scope")
                or (agentic and fault_ok)
                or truth["scope"] == "host")
    iou = _window_iou((dx.get("incident_window") or ""), truth["window"])
    # headline: microservice needs type AND place; agentic needs the type (there is no service
    # to name - the cap is on the run's own cgroup).
    detected = fault_ok and (where_ok if not agentic else True)
    return {"detected": bool(detected), "control": False, "present": True,
            "fault_ok": fault_ok, "where": where, "where_ok": bool(where_ok),
            "window_iou": iou, "family": fam, "agentic": agentic}


def _secs(s: str):
    try:
        p = [float(x) for x in str(s).strip().split(":")]
        while len(p) < 3:
            p.insert(0, 0.0)
        return p[0] * 3600 + p[1] * 60 + p[2]
    except (ValueError, AttributeError):
        return None


def _window_iou(pred_window: str, true_window) -> float | None:
    """Intersection-over-union of the predicted incident window and the true one. None when
    either side is unavailable (agentic has no injection window)."""
    if not true_window or not pred_window:
        return None
    m = re.findall(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", str(pred_window))
    if len(m) < 2:
        return None
    pa, pb = _secs(m[0]), _secs(m[1])
    ta, tb = _secs(true_window[0]), _secs(true_window[1])
    if None in (pa, pb, ta, tb) or pb <= pa or tb <= ta:
        return None
    inter = max(0.0, min(pb, tb) - max(pa, ta))
    union = max(pb, tb) - min(pa, ta)
    return round(inter / union, 3) if union > 0 else 0.0


if __name__ == "__main__":
    # self-check: both gt shapes, a hit, a miss, a control
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # microservice-style
        json.dump({"fault": {"name": "svc_mem_cap_carts", "scope": "service",
                             "target_service": "carts",
                             "injection_start_utc": "2026-09-05T15:19:46Z",
                             "injection_end_utc": "2026-09-05T15:21:46Z"}},
                  open(os.path.join(td, "ground_truth.json"), "w"))
        hit = score({"root_cause_service": "carts", "fault_type": "memory cap",
                     "incident_window": "15:19:46 - 15:21:46"}, td, "svc_mem_cap")
        assert hit["detected"] and hit["where"] == "named" and hit["window_iou"] == 1.0, hit
        miss = score({"root_cause_service": "front-end", "fault_type": "network"}, td,
                     "svc_mem_cap")
        assert not miss["detected"], miss
        # agentic control (no limit set = uncapped baseline)
        os.makedirs(os.path.join(td, "meta"))
        os.remove(os.path.join(td, "ground_truth.json"))
        json.dump({"cpu_max": "max"},
                  open(os.path.join(td, "meta", "ground_truth.json"), "w"))
        ctrl = score({"fault_type": "normal", "root_cause_service": ""}, td, "svc_cpu_cap")
        assert ctrl["control"] and ctrl["detected"], ctrl
        # agentic fault
        json.dump({"cpu_max": "max", "mem_limit": "high:640M"},
                  open(os.path.join(td, "meta", "ground_truth.json"), "w"))
        af = score({"fault_type": "memory_limit (cgroup reclaim)",
                    "root_cause_service": "ttmem"}, td, "svc_mem_cap")
        assert af["detected"] and af["agentic"], af
        print("score.py self-check OK")
