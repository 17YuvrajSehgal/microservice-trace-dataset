#!/usr/bin/env python3
"""Combine the three measurements into one verdict for the datastore-wait blueprint.

Takes the convergence point (traces), the blocking-syscall profile (kernel) and the
runqueue-delay control (kernel), and decides whether the evidence actually supports this
problem. It is willing to say NO: if runqueue delay inflated broadly, it points at the
CPU-contention blueprint instead.

    python3 dependency_verdict.py --convergence conv.json --blocking blocking.json \
        --rq rq.json --out verdict.json --chart blocking.svg --text explanation.txt
"""
from __future__ import annotations
import argparse, json, os, sys

# thresholds are MEASURED, not guessed - see the blueprint discriminators and evidence/
BLOCK_X = 5.0     # datastore fault measured 36.8x; CPU-fault control on same syscall was 1.12x
RQ_FLAT_X = 2.0   # datastore fault measured 1.09x; CPU fault measured 7.12x
SOCKET_CALLS = ("poll", "epoll_wait", "epoll_pwait", "recvfrom", "recvmsg", "read", "select")


def load(p):
    return json.load(open(p, encoding="utf-8")) if p and os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--convergence", default="")
    ap.add_argument("--blocking", required=True)
    ap.add_argument("--rq", default="")
    ap.add_argument("--out", default="verdict.json")
    ap.add_argument("--chart", default="")
    ap.add_argument("--text", default="")
    a = ap.parse_args()

    conv, block, rq = load(a.convergence), load(a.blocking), load(a.rq)
    if not block:
        sys.exit(f"blocking profile not found: {a.blocking}")

    # --- the decisive signal: one socket-waiting syscall inflating a lot ----------------
    rows = block.get("comparison", [])
    socket_rows = [r for r in rows
                   if r["comm_syscall"].split("|")[-1] in SOCKET_CALLS
                   and (r.get("p95_x") or 0) >= BLOCK_X]
    socket_rows.sort(key=lambda r: -(r["p95_x"] or 0))
    top = socket_rows[0] if socket_rows else None
    max_any = max((r.get("p95_x") or 0) for r in rows) if rows else 0.0

    # --- the control: is it merely CPU-starved? -----------------------------------------
    rq_max = rq_med = None
    if rq:
        big = [r for r in rq.get("comparison", []) if r.get("n_incident", 0) >= 500]
        xs = sorted(r["p95_x"] for r in big if r.get("p95_x"))
        if xs:
            rq_max, rq_med = xs[-1], xs[len(xs) // 2]

    reasons, supports = [], True
    if top:
        comm, call = top["comm_syscall"].split("|")
        reasons.append(f"{comm} blocked in {call} for {top['p95_x']}x its baseline "
                       f"(p95 {top['p95_baseline_ms']} -> {top['p95_incident_ms']} ms, "
                       f"n={top['n_incident']})")
    else:
        supports = False
        reasons.append(f"no socket-waiting syscall inflated by {BLOCK_X}x or more "
                       f"(largest inflation of any syscall was {max_any}x) - this does not "
                       f"look like a component blocked on a dependency")

    if rq_max is not None:
        if rq_max >= RQ_FLAT_X:
            supports = False
            reasons.append(f"runqueue delay inflated up to {rq_max}x (median {rq_med}x) - the "
                           f"processes are short of CPU. Use the CPU-contention blueprint")
        else:
            reasons.append(f"runqueue delay stayed flat (max {rq_max}x, median {rq_med}x), so "
                           f"the component is not short of CPU - it is waiting for a reply")
    else:
        reasons.append("no runqueue-delay control was supplied; CPU starvation was NOT ruled out")

    culprit = top["comm_syscall"].split("|")[0] if top else None
    conv_on = (conv or {}).get("converged_on")
    if conv_on:
        reasons.append(f"slow call edges converge on {conv_on}")
        if culprit and conv_on != culprit:
            reasons.append(f"NOTE: traces name {conv_on} but the kernel shows {culprit} is the "
                           f"one blocked - {conv_on} is a victim, and {culprit} emits no spans")

    verdict = {
        "supports_dependency_wait": supports,
        "blocked_component": culprit,
        "blocking_call": top["comm_syscall"].split("|")[-1] if top else None,
        "blocking_inflation_x": top["p95_x"] if top else None,
        "trace_convergence": conv_on,
        "runqueue_control": {"max_x": rq_max, "median_x": rq_med, "flat": (rq_max or 0) < RQ_FLAT_X},
        "thresholds": {"blocking_x": BLOCK_X, "runqueue_flat_x": RQ_FLAT_X,
                       "basis": "measured: 36.8x vs 1.12x blocking, 1.09x vs 7.12x runqueue"},
        "reasons": reasons,
        "top_inflated_calls": rows[:8],
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(verdict, open(a.out, "w"), indent=2)
    print(f"wrote {a.out}  (supports={supports}, blocked={culprit}, "
          f"call={verdict['blocking_call']}, x={verdict['blocking_inflation_x']})")

    if a.chart and rows:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            sel = rows[:10][::-1]
            names = [r["comm_syscall"] for r in sel]
            y = range(len(sel))
            fig, ax = plt.subplots(figsize=(9, 0.42 * len(sel) + 2))
            ax.barh([i - 0.2 for i in y], [r["p95_baseline_ms"] for r in sel], height=0.4,
                    label="baseline p95")
            ax.barh([i + 0.2 for i in y], [r["p95_incident_ms"] for r in sel], height=0.4,
                    label="incident p95")
            ax.set_yticks(list(y)); ax.set_yticklabels(names, fontsize=7)
            ax.set_xscale("log"); ax.set_xlabel("syscall duration p95 (ms, log scale)")
            ax.legend(fontsize=8)
            fig.tight_layout(); fig.savefig(a.chart); plt.close(fig)
            print(f"wrote {a.chart}")
        except Exception as e:                                          # noqa: BLE001
            print(f"chart skipped: {type(e).__name__}: {e}")

    if a.text:
        lines = ["Does the evidence support a component blocked on a dependency? "
                 + ("YES" if supports else "NO"), ""]
        lines += [f"- {r}" for r in reasons]
        open(a.text, "w").write("\n".join(lines) + "\n")
        print(f"wrote {a.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
