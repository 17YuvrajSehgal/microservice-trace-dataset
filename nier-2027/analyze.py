#!/usr/bin/env python3
"""Score the E2 ablation: accuracy by cell, plus the context attrition profile.

Accuracy uses the WHERE axis (did the agent name the correct culprit PROCESS),
scored independently of the fault label - see DESIGN.md amendment A4.

    python nier-2027/analyze.py
"""
from __future__ import annotations
import argparse, collections, glob, json, os, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "nier-2027", "results")
TRN = os.path.join(ROOT, "nier-2027", "transcripts")

# The culprit each class should name. Resident = the coding agent's own process tree,
# which is what the cgroup cap throttles. Spawned = the workers xargs launches.
CULPRIT = {
    "resident": ("claude", "node", "python3"),
    "spawned":  ("ttworker",),
    "healthy":  (),
}
# Words that mean "I found nothing" - the honest answer on a healthy run.
ABSTAIN = ("normal", "unknown", "none", "no fault", "healthy", "")


def dx_text(dx: dict) -> str:
    return " ".join(str(dx.get(k, "")) for k in
                    ("root_cause_service", "culprit_kind", "what_is_wrong", "evidence")).lower()


# NB: no empty string here - `rcs.startswith("")` is always True and silently
# scores every answer as an abstention.
NON_ANSWERS = ("unknown", "none", "n/a", "null", "unclear", "not established",
               "no fault", "not identified")


def score(rec: dict) -> dict:
    """Score the COMMITMENT, never a mention.

    An earlier version of this scorer searched the whole diagnosis prose for a
    culprit name. That credited sentences like "the later python3 workload is
    actively consuming cpu" as a successful localisation, on runs whose
    root_cause_service read "unknown". It inflated the resident arm from 3/15 to
    14/15 and would have manufactured an effect. The agent commits through
    root_cause_service; prose that merely names a process is not an answer.
    """
    dx = ((rec.get("result") or {}).get("diagnosis") or {})
    klass = rec["klass"]
    rcs = str(dx.get("root_cause_service", "")).strip().lower()
    kind = str(dx.get("culprit_kind", "")).strip().lower()
    committed = bool(rcs) and not any(rcs == n or rcs.startswith(n)
                                      for n in NON_ANSWERS)
    answer = f"{rcs} {kind}"
    named = [c for c in CULPRIT[klass] if c in answer] if committed else []
    prose = [c for c in CULPRIT[klass] if c in dx_text(dx)]
    out = {
        "committed": committed,
        "named_culprit": bool(named),
        "matched": ",".join(named),
        "mentioned_not_committed": bool(prose) and not committed,
        "root_cause_service": str(dx.get("root_cause_service", ""))[:60],
        "fault_label": str(dx.get("fault_type", "")).lower(),
        "abstained": not committed,
        "confidence": dx.get("confidence"),
    }
    if klass == "healthy":
        # The is-anything-wrong claim is the LABEL, not root_cause_service: runs
        # that answer fault_type=normal while describing the dominant process in
        # rcs are correct healthy verdicts, not false alarms. A false alarm is a
        # non-normal label (audited 20 Oct: 3 of 4 "committed" healthy cells had
        # label=normal and prose saying nothing is wrong).
        out["false_alarm"] = out["fault_label"] not in ("normal", "", "unknown")
        out["correct"] = not out["false_alarm"]
    else:
        out["correct"] = out["named_culprit"]
    return out


def attrition(cell: str) -> dict:
    p = os.path.join(TRN, cell + ".json")
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    ev = d.get("events") or []
    te = [e for e in ev if e.get("type") == "tool_execution"]
    we = [e for e in ev if e.get("type") == "worker_end"]
    fi = [e for e in ev if e.get("type") == "finding"]

    def _int(x, d=0):
        try: return int(x)
        except Exception: return d

    unparse = 0
    for e in te:
        s = e.get("sent")
        if isinstance(s, str) and s.strip().startswith("{"):
            try: json.loads(s)
            except Exception: unparse += 1
    return {
        "n_tool_calls": len(te),
        "n_truncated": sum(1 for e in te if e.get("truncated")),
        "n_sent_unparseable": unparse,
        "n_workers": len(we),
        "n_out_of_steps": sum(1 for e in we if str(e.get("ran_out_of_steps")).lower() == "true"),
        "max_thread_chars": max([_int(e.get("final_thread_chars")) for e in we] or [0]),
        "n_findings": len(fi),
        "n_code_snippets": len([e for e in ev if e.get("type") == "tool_execution"
                                and e.get("tool") == "run_python"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--csv"); a = ap.parse_args()
    rows = []
    for f in sorted(glob.glob(os.path.join(RES, "*.json"))):
        r = json.load(open(f, encoding="utf-8"))
        if r.get("status") != "ok":
            rows.append({**{k: r.get(k) for k in ("config", "klass", "run", "rep", "cell")},
                         "status": r.get("status"), "correct": None}); continue
        res = r["result"]
        rows.append({**{k: r[k] for k in ("config", "klass", "run", "rep", "cell")},
                     "status": "ok", **score(r),
                     "tokens_in": (res.get("tokens") or {}).get("in"),
                     "wall_s": res.get("wall_s"),
                     "n_computed": res.get("n_computed"),
                     "n_findings_run": res.get("n_findings"),
                     **attrition(r["cell"])})
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"{len(rows)} cells, {len(ok)} ok, {len(rows)-len(ok)} not ok\n")
    if not ok:
        return 0

    # ---- H2: the interaction ----
    print("=== accuracy: named the correct culprit process (WHERE) ===")
    print(f"{'config':<13}{'class':<10}{'n':>4}{'commit':>8}{'correct':>9}{'rate':>7}"
          f"{'mention-only':>14}")
    grid = collections.defaultdict(list)
    for r in ok:
        grid[(r["config"], r["klass"])].append(r)
    for (cfg, kl) in sorted(grid):
        g = grid[(cfg, kl)]
        c = sum(1 for x in g if x["correct"])
        cm = sum(1 for x in g if x.get("committed"))
        mo = sum(1 for x in g if x.get("mentioned_not_committed"))
        print(f"{cfg:<13}{kl:<10}{len(g):>4}{cm:>8}{c:>9}{100*c/len(g):>6.0f}%{mo:>14}")

    def rate(cfg, kl):
        g = grid.get((cfg, kl)) or []
        return (sum(1 for x in g if x["correct"]) / len(g)) if g else None

    print("\n=== H2: does the delivery defect hurt RESIDENT culprits more than SPAWNED? ===")
    for kl in ("resident", "spawned"):
        a_, b_ = rate("repair", kl), rate("s1_deliver", kl)
        if a_ is None or b_ is None:
            print(f"  {kl:<10} incomplete"); continue
        print(f"  {kl:<10} repair {100*a_:5.0f}%  ->  defect {100*b_:5.0f}%   "
              f"drop {100*(a_-b_):+5.0f} pts")

    # ---- H1: capacity was never the constraint ----
    tok = [r["tokens_in"] for r in ok if r.get("tokens_in")]
    if tok:
        print(f"\n=== H1: context use ===")
        print(f"  median input tokens/run : {statistics.median(tok):,.0f}")
        print(f"  max input tokens/run    : {max(tok):,.0f}")

    # ---- H3 / H4: attrition ----
    print("\n=== attrition profile by config ===")
    print(f"{'config':<13}{'tools':>7}{'trunc':>7}{'unparse':>9}{'oos':>6}{'find':>6}{'comp':>6}")
    for cfg in sorted({r["config"] for r in ok}):
        g = [r for r in ok if r["config"] == cfg]
        def m(k): 
            v = [r.get(k) for r in g if r.get(k) is not None]
            return statistics.mean(v) if v else 0
        print(f"{cfg:<13}{m('n_tool_calls'):>7.1f}{m('n_truncated'):>7.1f}"
              f"{m('n_sent_unparseable'):>9.1f}{m('n_out_of_steps'):>6.1f}"
              f"{m('n_findings'):>6.1f}{m('n_computed'):>6.1f}")

    if a.csv:
        import csv
        cols = sorted({k for r in rows for k in r})
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
