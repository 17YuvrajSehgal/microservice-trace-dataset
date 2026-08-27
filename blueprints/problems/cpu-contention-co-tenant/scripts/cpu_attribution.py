#!/usr/bin/env python3
"""Final step of the CPU-contention blueprint: who took the CPU, and who waited for it.

Measures and reports. It does NOT assume the answer: if the evidence does not support a
co-tenant reading, it says so in the verdict rather than forcing one.

Inputs
  --run    a run directory (needs metrics/ and meta/; kernel_l2.jsonl if wait shares wanted)
  --wait   kernel_l2.jsonl (optional; without it the wait-share section is reported absent)

Outputs
  --out    verdict.json    machine verdict + the numbers behind it
  --chart  runqueue.svg    per-service wait shares, and CPU by container over time
  --text   explanation.txt plain-language reasoning

    python3 cpu_attribution.py --run <run_dir> --wait <run>/kernel_l2.jsonl \
        --out verdict.json --chart runqueue.svg --text explanation.txt
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "agentic-rca"))


def load_wait(path):
    if not path or not os.path.exists(path):
        return {}
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[r.get("service", "?")] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--wait", default="")
    ap.add_argument("--out", default="verdict.json")
    ap.add_argument("--chart", default="")
    ap.add_argument("--text", default="")
    a = ap.parse_args()

    from stratatrace import load_run
    from tools import RunTools

    run = load_run(a.run)
    t = RunTools(run, app=a.app)

    # --- 1. which containers consumed CPU, and which are on the call path ---------------
    metrics, _ = t.metrics(None)
    movers = metrics.get("top_movers", []) if isinstance(metrics, dict) else []
    cpu = {}
    for m in movers:
        if m.get("signal") == "cpu_cores":
            cpu[m["container"]] = {"baseline": m.get("baseline"), "incident": m.get("incident"),
                                   "rel_change": m.get("rel_change")}

    topo, _ = t.topology(None)
    on_path = set()
    for e in (topo.get("edges", []) if isinstance(topo, dict) else []):
        on_path.add(e.get("caller"))
        on_path.add(e.get("callee"))

    host, _ = t.host_metrics()
    host_cpu = host.get("host_cpu_busy_cores", {}) if isinstance(host, dict) else {}

    # a co-tenant is a container that consumed CPU but has no call-path role
    candidates = []
    for c, v in cpu.items():
        inc, base = v.get("incident") or 0.0, v.get("baseline") or 0.0
        if inc <= 0.05:                                    # ignore idle containers
            continue
        candidates.append({"container": c, "cpu_baseline": base, "cpu_incident": inc,
                           "appeared": base <= 0.01 < inc,
                           "on_call_path": c in on_path})
    candidates.sort(key=lambda x: -x["cpu_incident"])
    off_path = [c for c in candidates if not c["on_call_path"]]

    # --- 2. what the affected services were waiting for --------------------------------
    waits = load_wait(a.wait or os.path.join(a.run, "kernel_l2.jsonl"))
    wait_rows = []
    for svc, r in waits.items():
        s = r.get("rule_out_pct", {})
        wait_rows.append({"service": svc, **{k: s.get(k) for k in
                          ("on_cpu", "runnable_wait", "disk_wait", "off_cpu_io_wait")},
                          "verdict_hint": r.get("verdict_hint")})
    wait_rows.sort(key=lambda r: -(r.get("runnable_wait") or 0))

    # --- 3. verdict, stated only as far as the evidence goes ---------------------------
    reasons, supports = [], True
    if off_path:
        top = off_path[0]
        reasons.append(f"{top['container']} consumed {top['cpu_incident']:.2f} cores during the "
                       f"incident (baseline {top['cpu_baseline']:.2f}) and has no call-path edges")
        if top["appeared"]:
            reasons.append(f"{top['container']} was absent in the baseline and appeared mid-run")
    else:
        supports = False
        reasons.append("no off-call-path container consumed meaningful CPU - this does not look "
                       "like co-tenant contention")

    if wait_rows:
        worst = wait_rows[0]
        reasons.append(f"highest runnable-wait share: {worst['service']} at "
                       f"{worst.get('runnable_wait')}% (on_cpu {worst.get('on_cpu')}%)")
    else:
        reasons.append("NO wait-share data available (kernel_l2.jsonl absent) - the "
                       "runnable-vs-blocked distinction could not be checked")

    if host_cpu:
        reasons.append(f"host CPU busy cores {host_cpu.get('baseline')} -> "
                       f"{host_cpu.get('incident')} (x{host_cpu.get('change_x')})")

    verdict = {
        "run": os.path.basename(a.run.rstrip("/")),
        "supports_co_tenant_contention": supports,
        "suspected_culprit": off_path[0]["container"] if off_path else None,
        "cpu_by_container": candidates[:10],
        "off_call_path_consumers": off_path[:5],
        "wait_shares": wait_rows[:10],
        "host_cpu": host_cpu,
        "reasons": reasons,
        "evidence_gaps": ([] if wait_rows else ["kernel_l2.jsonl not derived for this run"]),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(verdict, open(a.out, "w"), indent=2, default=str)
    print(f"wrote {a.out}  (supports={supports}, culprit={verdict['suspected_culprit']})")

    # --- 4. chart ----------------------------------------------------------------------
    if a.chart and wait_rows:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            rows = wait_rows[:8]
            names = [r["service"] for r in rows]
            keys = ("on_cpu", "runnable_wait", "disk_wait", "off_cpu_io_wait")
            fig, ax = plt.subplots(figsize=(9, 0.5 * len(rows) + 2))
            left = [0.0] * len(rows)
            for k in keys:
                vals = [float(r.get(k) or 0) for r in rows]
                ax.barh(names, vals, left=left, label=k)
                left = [l + v for l, v in zip(left, vals)]
            ax.set_xlabel("share of wall time during the incident (%)")
            ax.legend(fontsize=7, ncol=4)
            ax.invert_yaxis()
            fig.tight_layout()
            fig.savefig(a.chart)
            plt.close(fig)
            print(f"wrote {a.chart}")
        except Exception as e:                                          # noqa: BLE001
            print(f"chart skipped: {type(e).__name__}: {e}")

    # --- 5. explanation ----------------------------------------------------------------
    if a.text:
        lines = [f"Run: {verdict['run']}", ""]
        lines.append("Does the evidence support co-tenant CPU contention? "
                     + ("YES" if supports else "NO"))
        lines.append("")
        for r in reasons:
            lines.append(f"- {r}")
        if verdict["evidence_gaps"]:
            lines += ["", "Gaps (claims that could NOT be checked here):"]
            for g in verdict["evidence_gaps"]:
                lines.append(f"- {g}")
        open(a.text, "w").write("\n".join(lines) + "\n")
        print(f"wrote {a.text}")


if __name__ == "__main__":
    sys.exit(main())
