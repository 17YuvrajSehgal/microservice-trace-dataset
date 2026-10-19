#!/usr/bin/env python3
"""E1: the delivery cliff. Deterministic, no model calls, no data needed.

Shows that bounding a tool result by slicing its serialized JSON deletes late keys
outright, and that WHICH keys die is decided by how long the earlier lists happen to
be - a property of the workload, not of the question being asked.

This is the mechanism behind the field measurement: over 742 real calls, the late key
`present_throughout` reached the model in 4.7% of them while its sibling early key
reached it 99.3% of the time.

    python mechanism_delivery.py            # table
    python mechanism_delivery.py --csv out.csv
"""
from __future__ import annotations
import argparse, importlib, json, os, sys

AGENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Blueprint", "agent")
sys.path.insert(0, os.path.abspath(AGENT))

V1_CAP = 6000          # what v1 shipped
RESIDENT = 25          # already-running containers; the late key


def _utils(flat_cap: int):
    os.environ["ABL_FLAT_CAP"] = str(flat_cap)
    sys.modules.pop("utils", None)
    return importlib.import_module("utils")


def proclife(n_spawned: int, n_resident: int = RESIDENT) -> dict:
    """The shape ctf_proclife returns. Early key = spawned, late key = resident."""
    return {
        "present_for_only_part_of_the_recording": [
            {"procname": "stress-ng-cpu", "pid_ns": 4026533600 + i,
             "first_s": 61.0, "last_s": 181.0, "n_events": 12345 + i}
            for i in range(n_spawned)],
        "present_throughout": [
            {"procname": "java", "pid_ns": 4026532700 + i, "n_events": 918273 + i}
            for i in range(n_resident)],
        "n_containers_seen": n_resident + n_spawned,
        "how_to_read": "absent in baseline then present = SPAWNED; present throughout = resident",
    }


def delivered(txt: str, key: str) -> int:
    """Rows of `key` the model can actually USE. Unparseable payload => zero."""
    try:
        obj = json.loads(txt)
    except Exception:
        return 0
    return len(obj.get(key) or []) if isinstance(obj, dict) else 0


def sweep(spawn_counts) -> list[dict]:
    rows = []
    for n in spawn_counts:
        obj = proclife(n)
        rec = {"n_spawned": n, "result_chars": len(json.dumps(obj))}
        for label, flat in (("defect", V1_CAP), ("repair", 0)):
            u = _utils(flat)
            # Under repair the per-tool budget applies; under the defect it is ignored.
            txt, cut, _ = u.fit_result(obj, 60000)
            try:
                json.loads(txt); valid = True
            except Exception:
                valid = False
            rec[f"{label}_late_rows"] = delivered(txt, "present_throughout")
            rec[f"{label}_early_rows"] = delivered(
                txt, "present_for_only_part_of_the_recording")
            rec[f"{label}_valid_json"] = valid
            rec[f"{label}_truncated"] = bool(cut)
        rows.append(rec)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--max-spawned", type=int, default=160)
    a = ap.parse_args()

    counts = [n for n in (5, 10, 20, 30, 40, 60, 80, 120, 160) if n <= a.max_spawned]
    rows = sweep(counts)

    print(f"late key = present_throughout ({RESIDENT} resident containers = "
          f"already-running culprits)")
    print(f"v1 flat cap = {V1_CAP} chars, applied as a prefix slice of the JSON string\n")
    print(f"{'spawned':>8}{'chars':>8} | {'defect late':>12}{'valid':>7} | "
          f"{'repair late':>12}{'valid':>7}")
    print("-" * 62)
    for r in rows:
        print(f"{r['n_spawned']:>8}{r['result_chars']:>8} | "
              f"{str(r['defect_late_rows']) + '/' + str(RESIDENT):>12}"
              f"{str(r['defect_valid_json']):>7} | "
              f"{str(r['repair_late_rows']) + '/' + str(RESIDENT):>12}"
              f"{str(r['repair_valid_json']):>7}")

    cliff = next((r["n_spawned"] for r in rows if r["defect_late_rows"] == 0), None)
    print(f"\nthe late key becomes unusable once the result exceeds the cap "
          f"(at {cliff} spawned processes here).")
    print("nothing about the diagnostic question changed - only how many short-lived "
          "processes the trace happened to contain.")

    if a.csv:
        import csv
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
