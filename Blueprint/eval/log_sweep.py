#!/usr/bin/env python3
"""Score the log tools on labelled runs: the four numbers of LOGS-PLAN.md section 8.

SCORER-SIDE. It reads ground_truth.json, so nothing an agent can reach may import it (same rule
as nsmap.py). The tools themselves never see a label.

    python Blueprint/eval/log_sweep.py --runs runs.txt --index-dir DIR --out sweep.jsonl

Per run (one JSON line), using the tools' own code (logkit.tools):
    onset      log_onset's first change: time, entity, signal. Scored against the injection:
               seconds after it, and whether it lands before it (a false alarm: the logs changed
               while nothing was injected yet)
    role       which entities log_onset finds changing while the fault is on (from EARLY_S
               before the injection to its end): the target among them (culprit logs it),
               only others, or none (silent). Scored over the whole fault, because a slice at a
               fixed offset missed short bursts (disk_full: carts-db crashed 9 s in, then went quiet)
    window     log_window on a fault slice (injection +WIN_AFTER_S, WIN_S long) against a baseline
               slice that ends BASE_GAP_S before the injection: what a blueprint step would see
    drops      line-rate drops (not counted as changes; open decision 12.3): the first one after
               the injection, and how many came before it. Reported for entities of any rate and
               of at least DROP_BUSY lines per second
Normal runs have no injection; the anchor is NORMAL_ANCHOR_S after the first log line, and any
LOG ONSET or LOG DIFF on them is a false alarm.

Then a table per family, printed as Markdown.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # Blueprint/

from logkit.tools import log_onset, logsig  # noqa: E402
from logkit.tools import logidx as L  # noqa: E402

WIN_AFTER_S = 30          # the fault slice starts this long after the injection
WIN_S = 20
BASE_S = 20
BASE_GAP_S = 5            # the baseline slice ends this long before the injection
NORMAL_ANCHOR_S = 90      # a normal run's pretend injection time, after its first log line
EARLY_S = 5               # an onset more than this before the injection is a false alarm
ON_TIME_S = 30            # an onset within this after the injection is "on time" (open, 12.2)
FAULT_S = 120             # a fault's length when its label gives no end (normal runs, old labels)
DROP_BUSY = 20            # lines/s; queue-master and shipping (~6/s) only log at the start of a run


def truth(run: Path) -> dict:
    p = run / "ground_truth.json"
    if not p.exists():
        return {"normal": True, "target": None, "start": None, "end": None}
    f = json.loads(p.read_text()).get("fault") or {}
    def epoch(s):
        return L.resolve_time(s.replace("T", " ").rstrip("Z"), 0) if s else None

    return {"normal": False, "target": f.get("target_service"),
            "start": epoch(f.get("injection_start_utc")), "end": epoch(f.get("injection_end_utc"))}


def family(run_id: str) -> str:
    for cut in ("_aggressive", "_subtle", "_none"):
        if cut in run_id:
            return run_id.split(cut)[0]
    return run_id.rsplit("_r", 1)[0]


def score_run(run: Path, index: Path) -> dict:
    t = truth(run)
    idx = L.load(str(index))
    row = {"run": run.name, "family": family(run.name), "normal": t["normal"], "target": t["target"],
           "lines": idx.lines}
    if not idx.lines or idx.t0 is None:
        return {**row, "note": "no logs"}
    inj = t["start"] if t["start"] is not None else idx.t0 + NORMAL_ANCHOR_S
    row["inj"] = L.hms(inj)
    base_end = idx.t0 + log_onset.WARMUP_S + log_onset.BASE_S
    row["inj_in_baseline"] = inj < base_end        # the onset tool cannot see a fault this early

    changes, _ = log_onset.find_changes(idx)
    real = [c for c in changes if c.signal != "drop"]
    if real:
        c = real[0]
        row["onset"] = {"t": L.hms(c.t), "dt": round(c.t - inj, 1), "entity": c.entity,
                        "signal": c.signal, "what": c.what[:160],
                        "is_target": c.entity == t["target"]}
    end = t["end"] or inj + FAULT_S
    during = {c.entity for c in real if inj - EARLY_S <= c.t <= end}
    row["onset_entities"] = sorted(during)
    if t["normal"]:
        row["role"] = "n/a"
    elif t["target"] in during:
        row["role"] = "culprit_logs"
    else:
        row["role"] = "others_only" if during else "silent"

    busy = {n for n, e in idx.entities.items() if e.lines_in(*base_win(idx, inj)) / BASE_S >= DROP_BUSY}
    drops = [c for c in changes if c.signal == "drop"]
    for key, ds in (("drop", drops), ("drop_busy", [c for c in drops if c.entity in busy])):
        after = [c for c in ds if c.t >= inj - EARLY_S]
        row[key] = {"first_dt": round(after[0].t - inj, 1) if after else None,
                    "first_entity": after[0].entity if after else None,
                    "before_injection": sum(1 for c in ds if c.t < inj - EARLY_S)}

    win = (inj + WIN_AFTER_S, inj + WIN_AFTER_S + WIN_S)
    base = base_win(idx, inj)
    diffs = [logsig.diff(e, base, win) for e in idx.entities.values() if e.lines]
    changed = {d.entity: d.describe() for d in diffs if d.changed}
    row["window"] = changed
    row["window_drops"] = sorted(d.entity for d in diffs if d.drop)
    return row


def base_win(idx, inj):
    return (inj - BASE_GAP_S - BASE_S, inj - BASE_GAP_S)


def summarise(rows: list[dict]) -> str:
    out = []
    normal = [r for r in rows if r["normal"]]
    if normal:
        fa_on = sum(1 for r in normal if r.get("onset"))
        fa_win = sum(1 for r in normal if r.get("window"))
        fa_drop = sum(1 for r in normal if (r.get("drop_busy") or {}).get("first_dt") is not None
                      or (r.get("drop_busy") or {}).get("before_injection"))
        out.append("**Normal runs: %d.** False alarms: log_onset %d, log_window %d. "
                   "Busy line-rate drops (not counted as changes): %d." % (
                       len(normal), fa_on, fa_win, fa_drop))
        for r in normal:
            if r.get("onset") or r.get("window"):
                out.append("- %s: onset %s; window %s" % (
                    r["run"], json.dumps(r.get("onset")), json.dumps(r.get("window"))))
        out.append("")
    out.append("| family | runs | onset found | before injection (false alarm) | on time (<= %d s) "
               "| median dt s | onset entity = target | role: culprit logs / others only / silent "
               "| window slice changed | busy drop: on time / before injection |" % ON_TIME_S)
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    by = defaultdict(list)
    for r in rows:
        if not r["normal"]:
            by[r["family"]].append(r)
    for fam, rs in sorted(by.items()):
        ons = [r["onset"] for r in rs if r.get("onset")]
        early = [o for o in ons if o["dt"] < -EARLY_S]
        ontime = [o for o in ons if -EARLY_S <= o["dt"] <= ON_TIME_S]
        dts = [o["dt"] for o in ons if o["dt"] >= -EARLY_S]
        roles = defaultdict(int)
        for r in rs:
            roles[r.get("role", "no logs")] += 1
        bd = [r.get("drop_busy") or {} for r in rs]
        out.append("| %s | %d | %d | %d | %d | %s | %d | %d / %d / %d | %d | %d / %d |" % (
            fam, len(rs), len(ons), len(early), len(ontime),
            "%.1f" % statistics.median(dts) if dts else "-",
            sum(1 for o in ons if o["is_target"]),
            roles["culprit_logs"], roles["others_only"], roles["silent"],
            sum(1 for r in rs if r.get("window")),
            sum(1 for d in bd if d.get("first_dt") is not None and d["first_dt"] <= ON_TIME_S),
            sum(1 for d in bd if d.get("before_injection"))))
    inb = [r["run"] for r in rows if r.get("inj_in_baseline") and not r["normal"]]
    if inb:
        out.append("")
        out.append("Injection inside the onset baseline (the onset tool cannot see it): " + ", ".join(inb))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True, help="file with one run directory per line")
    ap.add_argument("--index-dir", required=True)
    ap.add_argument("--out", required=True, help="one JSON line per run")
    a = ap.parse_args(argv)
    rows = []
    for line in Path(a.runs).read_text().split():
        run = Path(line)
        index = Path(a.index_dir) / f"{run.name}.logidx.json.gz"
        if not index.exists():
            print(f"no index for {run.name}", file=sys.stderr)
            continue
        rows.append(score_run(run, index))
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(summarise(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
