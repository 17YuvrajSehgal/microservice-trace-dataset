#!/usr/bin/env python3
"""Run the Blueprint agent on ONE trace with ONE blueprint, score the verdict, write result.json.

Everything comes from the Blueprint tree: the agent is Blueprint/agent, the blueprint is a
Blueprint/latency/*/README_v1.md, the scorer is score.py here. The index each run needs
(<run_id>.tsv.gz) is read from CTF_INDEX_ROOT.

    python eval_one.py --run-dir <dir> --blueprint <README_v1.md> --problem svc_mem_cap \
                       --index-root <dir> --out <dir>

Matched arm: --blueprint is the correct one for --problem. That answers "how often does the
agent detect the fault when handed the right blueprint." Omit --blueprint for the control
(no blueprint) arm.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # repo root
AGENT_DIR = os.path.join(ROOT, "Blueprint", "agent")
sys.path.insert(0, HERE)                               # score, nsmap
sys.path.insert(0, AGENT_DIR)                          # agent_v2, config, blueprints

import score as S  # noqa: E402


def run(run_dir, blueprint, problem, index_root, out_dir, transcript=None):
    os.environ["CTF_INDEX_ROOT"] = index_root
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    import agent_v2, config                            # noqa: E402

    t0 = time.time()
    dx = agent_v2.diagnose(run_dir, blueprint=blueprint, index_root=index_root,
                           transcript_path=transcript,
                           condition="eval|%s|%s" % (problem, "given" if blueprint else "none"))
    wall = round(time.time() - t0, 1)

    diagnosis = dx.get("diagnosis") or {}
    sc = S.score(diagnosis, run_dir, problem, index_root=index_root)
    toks = dx.get("tokens") or {}
    row = {
        "run_id": os.path.basename(run_dir.rstrip("/\\")),
        "problem": problem,
        "arm": "given" if blueprint else "none",
        "blueprint": os.path.basename(os.path.dirname(blueprint)) if blueprint else None,
        "model": config.model_id(), "provider": config.PROVIDER,
        "verdict": {"where": diagnosis.get("root_cause_service"),
                    "what_is_wrong": diagnosis.get("what_is_wrong"),
                    "when": diagnosis.get("incident_window"),
                    "fault": diagnosis.get("fault_type"),
                    "confidence": diagnosis.get("confidence")},
        "score": sc,
        "seconds": wall, "calls": dx.get("n_tool_calls"),
        "tokens_in": toks.get("in", 0), "tokens_out": toks.get("out", 0),
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        json.dump(row, open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8"),
                  indent=1, default=str)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--blueprint", default=None, help="README_v1.md; omit for the control arm")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--index-root", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--transcript", default=None)
    a = ap.parse_args()
    row = run(a.run_dir, a.blueprint, a.problem, a.index_root, a.out, a.transcript)
    print(json.dumps(row, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
