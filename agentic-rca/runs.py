#!/usr/bin/env python3
"""Enumerate labeled incidents + score a diagnosis against ground truth.

`iter_runs(app, root)` yields one record per fault incident (from loader.list_runs enriched with
ground_truth + the manifest's verification verdict). `score(diagnosis, gt)` compares the agent's
{root_cause_service, fault_type} to the labels → the Top-1 signals the evaluation runner aggregates.
"""
from __future__ import annotations
import csv, os, sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stratatrace import load_run, list_runs

DEFAULT_ROOT = os.environ.get("RUNS_ROOT", "/scratch/yuvraj17/agentic-runs")

# agent fault_type  ->  ground-truth recipe/family it corresponds to
FAULT_TO_FAMILY = {
    "cpu_saturation": "anomaly_cpu", "memory_pressure": "anomaly_mem", "disk_io": "anomaly_disk",
    "network_latency": "anomaly_net", "db_latency": "slow_db", "dependency_outage": "dependency_outage",
    "error_storm": "error_storm", "noisy_neighbor": "noisy_neighbor", "cpu_throttling": "svc_cpu_cap",
    "memory_limit": "svc_mem_cap", "service_network": "svc_net", "queue_backlog": "queue_backlog",
    "normal": "normal",
}


@dataclass
class RunRec:
    run_id: str
    app: str
    fault_family: str        # recipe dir name (anomaly_cpu, slow_db, …)
    dir: str
    target_service: str = ""
    expected_winning_modality: str = ""
    verification: str = ""   # confirmed | borderline | unconfirmed | n/a (from manifest)
    ground_truth: dict = field(default_factory=dict)


def _manifest_verification(app_root: str) -> dict:
    """run_id -> verification verdict, from the per-app manifest.csv if present."""
    out = {}
    mani = os.path.join(app_root, "manifest.csv")
    if not os.path.exists(mani):
        return out
    with open(mani, newline="") as fh:
        for row in csv.DictReader(fh):
            rid = row.get("run_id")
            if rid:
                out[rid] = row.get("verification", "")
    return out


def iter_runs(app: str, root: str = DEFAULT_ROOT):
    """Yield RunRec for every labeled fault incident of `app` (baseline/normal runs have no
    ground_truth.json and are skipped by list_runs — they're the negative controls)."""
    app_root = os.path.join(root, app)
    verif = _manifest_verification(app_root)
    for fam, run_id, rd in list_runs(app_root):
        gt = load_run(rd).ground_truth.get("fault", {})
        yield RunRec(run_id=run_id, app=app, fault_family=fam, dir=rd,
                     target_service=gt.get("target_service", ""),
                     expected_winning_modality=gt.get("expected_winning_modality", ""),
                     verification=verif.get(run_id, ""), ground_truth=gt)


def _norm(s: str) -> str:
    return (s or "").lower().replace("docker-compose_", "").replace("trainticket_", "").rstrip("_1").strip()


def score(diagnosis: dict, gt: dict, family: str = "") -> dict:
    """Compare a diagnosis to ground truth. `family` is the authoritative recipe (dir name, e.g.
    'anomaly_mem'); ground_truth['fault']['family'] is instead a taxonomy code (A_host_resource…),
    and ['name'] carries the recipe prefix ('slow_db_mysql'). Service match tolerates container-name
    decoration and the host-fault case (the culprit is the injected stress container)."""
    if not diagnosis:
        return {"service_hit": False, "fault_hit": False, "both": False, "no_answer": True}
    pred_svc = _norm(diagnosis.get("root_cause_service", ""))
    pred_fault = diagnosis.get("fault_type", "")
    tgt = _norm(gt.get("target_service", ""))
    name = str(gt.get("name", "")).lower()

    if tgt in ("host", "", "node"):
        service_hit = any(k in pred_svc for k in ("stress", "neighbor", "aggressor", "host", "anomaly"))
    else:
        service_hit = bool(pred_svc) and (pred_svc == tgt or tgt in pred_svc or pred_svc in tgt)

    recipe = FAULT_TO_FAMILY.get(pred_fault, pred_fault)   # agent fault_type → recipe name
    fault_hit = bool(recipe) and (recipe == family or name.startswith(recipe) or recipe in name)
    return {"service_hit": bool(service_hit), "fault_hit": bool(fault_hit),
            "both": bool(service_hit and fault_hit), "no_answer": False,
            "pred_service": pred_svc, "target": tgt, "pred_fault": pred_fault, "expected_family": family}


if __name__ == "__main__":
    app = sys.argv[1] if len(sys.argv) > 1 else "trainticket"
    recs = list(iter_runs(app))
    print(f"{app}: {len(recs)} labeled incidents")
    from collections import Counter
    print("families:", dict(Counter(r.fault_family for r in recs)))
    print("verification:", dict(Counter(r.verification for r in recs)))
    for r in recs[:8]:
        print(f"  {r.run_id:48s} fam={r.fault_family:16s} target={r.target_service:14s} "
              f"win={r.expected_winning_modality:8s} verif={r.verification}")
