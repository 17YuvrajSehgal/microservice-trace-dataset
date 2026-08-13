#!/usr/bin/env python3
"""Leakage auditor — proves, transcript by transcript, that the agent was never told the answer.

    python audit_leakage.py results/agent_sweep*.json          # audit everything a sweep produced
    python audit_leakage.py --transcripts dir/                 # or a directory of transcripts

For every transcript it reconstructs the MODEL-VISIBLE INPUT (system prompt, user message,
every tool-result string actually sent) and scans it for label leaks:

  HARD failures (exit 1 — these would invalidate the result):
    * the run id (encodes fault/intensity/workload) or any of its fault-name tokens
    * any fault-family/recipe token (slow_db, anomaly_cpu, noisy_neighbor, …, any separator style)
    * injection-infrastructure container names (anomaly-*-stress, noisy-neighbor, toxiproxy)
    * ground-truth vocabulary (ground_truth, target_service, expected_blast_radius,
      expected_winning_modality, injection_start_utc, blind_spot, fault_family)
  SOFT warnings (reported, not fatal — human judgement):
    * intensity/workload tokens (aggressive, subtle, burst) appearing in inputs
    * meta.mask_names false (the unmasked ablation is legitimate but must be deliberate)

Assistant OUTPUT text is not scanned — the model may hypothesize "a slow db" in its own
words; that is diagnosis, not leakage. Only what WE fed it counts.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import re
import sys

FAMILIES = [
    "anomaly_cpu", "anomaly_disk", "anomaly_mem", "anomaly_net", "slow_db", "error_storm",
    "svc_cpu_cap", "svc_mem_cap", "dependency_outage", "queue_backlog", "noisy_neighbor", "svc_net",
]
CONTAINERS = ["anomaly-cpu-stress", "anomaly-mem-stress", "anomaly-disk-stress",
              "noisy-neighbor", "toxiproxy"]
GT_VOCAB = ["ground_truth", "target_service", "expected_blast_radius", "expected_winning_modality",
            "injection_start_utc", "injection_end_utc", "blind_spot", "fault_family"]
SOFT = ["aggressive", "subtle", "burst"]


def _sep_variants(tok: str) -> str:
    """Regex matching the token under any separator style (slow_db / slow-db / slow db / slowdb)."""
    parts = re.split(r"[_-]", tok)
    return r"[\s_-]?".join(re.escape(p) for p in parts)


def _compile(tokens):
    return re.compile("|".join(sorted({_sep_variants(t) for t in tokens}, key=len, reverse=True)),
                      re.IGNORECASE)


# Static inputs (system prompt, tool schemas) are identical for every incident, so the closed
# fault-type taxonomy they contain is the answer SPACE, not a leak — scan them only for
# run-specific vocabulary. Per-incident inputs (user message, tool results) get the full scan.
# ("noisy-neighbor" the container is separator-identical to "noisy_neighbor" the taxonomy label,
# so it must be exempted from the static scan; it stays fully scanned in per-incident inputs.)
_HARD_FULL = _compile(FAMILIES + CONTAINERS + GT_VOCAB)
_HARD_STATIC = _compile([c for c in CONTAINERS if c != "noisy-neighbor"] + GT_VOCAB)
_SOFT = re.compile(r"\b(" + "|".join(SOFT) + r")\b", re.IGNORECASE)


def model_visible_input(doc: dict) -> list[tuple[str, str, bool]]:
    """(where, text, is_static) triples for everything the model was GIVEN."""
    out = []
    for e in doc.get("events", []):
        if e["type"] == "system_prompt":
            out.append(("system_prompt", e.get("text", ""), True))
        elif e["type"] == "user_message":
            out.append(("user_message", e.get("text", ""), False))
        elif e["type"] == "tools_schema":
            out.append(("tools_schema", json.dumps(e.get("tools", "")), True))
        elif e["type"] == "tool_execution":
            sent = e.get("sent")
            if sent is None:  # schema v1 pre-masking: sent was derivable from result
                sent = json.dumps(e.get("result", ""), default=str)[:6000]
            out.append((f"tool_result[{e.get('tool')}@step{e.get('step')}]", str(sent), False))
    return out


def audit_one(path: str) -> tuple[list[str], list[str]]:
    doc = json.load(open(path, encoding="utf-8"))
    hard, soft = [], []
    run_id = (doc.get("meta") or {}).get("run_id", "")
    run_pat = re.compile(re.escape(run_id), re.IGNORECASE) if run_id else None
    for where, text, is_static in model_visible_input(doc):
        if run_pat and run_pat.search(text):
            hard.append(f"{where}: contains the run id {run_id!r}")
        pat = _HARD_STATIC if is_static else _HARD_FULL
        for m in {mm.group(0) for mm in pat.finditer(text)}:
            hard.append(f"{where}: leak token {m!r}")
        if not is_static:
            for m in {mm.group(0).lower() for mm in _SOFT.finditer(text)}:
                soft.append(f"{where}: soft token {m!r}")
    if not (doc.get("meta") or {}).get("mask_names", False):
        soft.append("meta.mask_names is false/absent — unmasked ablation or pre-masking transcript")
    return hard, soft


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="*", help="results JSON file(s)/globs from evaluate.py")
    ap.add_argument("--transcripts", default="", help="audit every *.json under this directory instead")
    a = ap.parse_args()
    files: list[str] = []
    if a.transcripts:
        files = [p for p in glob.glob(os.path.join(a.transcripts, "**", "*.json"), recursive=True)]
    for pat in a.results:
        for rp in glob.glob(pat):
            doc = json.load(open(rp, encoding="utf-8"))
            tdir = (doc.get("meta") or {}).get("transcripts_dir")
            for row in doc.get("results", []):
                if row.get("transcript") and tdir:
                    p = os.path.join(tdir, row["transcript"])
                    if os.path.isfile(p):
                        files.append(p)
    files = sorted(set(files))
    if not files:
        raise SystemExit("no transcripts found to audit")
    n_hard = n_soft = 0
    for p in files:
        try:
            hard, soft = audit_one(p)
        except Exception as e:
            print(f"UNREADABLE {p}: {e}")
            n_hard += 1
            continue
        n_hard += len(hard)
        n_soft += len(soft)
        for h in hard:
            print(f"HARD {p}: {h}")
        for s in soft:
            print(f"soft {p}: {s}")
    verdict = "FAIL" if n_hard else "PASS"
    print(f"\n{verdict}: {len(files)} transcripts audited, {n_hard} hard leaks, {n_soft} soft warnings")
    sys.exit(1 if n_hard else 0)


if __name__ == "__main__":
    main()
