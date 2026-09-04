#!/usr/bin/env python3
"""Turn `lttng stop` output into a machine-readable verdict on whether a run lost events.

WHY THIS EXISTS
---------------
v1 ran `lttng stop || true` and threw the output away. LTTng reports discarded events and
lost packets there, and nowhere else. So a run that dropped a third of its `sched_switch`
events under peak stress produced a trace that looks exactly like a clean one - and every
ratio computed from it (on-CPU share, runqueue delay, interrupt time, retransmission
percentage) is silently wrong.

That risk is worst in exactly the runs we care about most: the heaviest faults, and any run
with the memory tracepoints enabled, because both raise buffer pressure.

A run with any loss is not automatically useless, but it must be visible, and the campaign
driver must be able to see it without parsing prose.

    python3 parse_event_loss.py <lttng_stop.txt> <event_loss.json>

Exit code is 0 for a clean run and 2 for a lossy one, so a caller can branch on it.
"""
from __future__ import annotations
import json, re, sys

# LTTng phrasing has varied across versions, so match on the numbers and the noun rather
# than on a whole sentence.
PATTERNS = [
    (r"([\d,]+)\s+events?\s+(?:were\s+)?discarded", "discarded_events"),
    (r"([\d,]+)\s+packets?\s+(?:were\s+)?lost", "lost_packets"),
    (r"discarded\s+([\d,]+)\s+events?", "discarded_events"),
    (r"lost\s+([\d,]+)\s+packets?", "lost_packets"),
]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    try:
        text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    except OSError as e:
        json.dump({"error": str(e), "clean": None}, open(sys.argv[2], "w"), indent=2)
        print(f"[loss] could not read {sys.argv[1]}: {e}")
        return 1

    totals = {"discarded_events": 0, "lost_packets": 0}
    hits = []
    for rx, key in PATTERNS:
        for m in re.finditer(rx, text, re.I):
            n = int(m.group(1).replace(",", ""))
            totals[key] += n
            hits.append({"key": key, "n": n, "text": m.group(0)})

    # "Waiting for data availability" with no warning line is the normal, clean case.
    clean = totals["discarded_events"] == 0 and totals["lost_packets"] == 0
    out = {**totals, "clean": clean, "matches": hits,
           "note": ("no discarded events or lost packets reported" if clean else
                    "THIS RUN LOST DATA - ratios computed from it may be wrong")}
    json.dump(out, open(sys.argv[2], "w"), indent=2)

    if clean:
        print("[loss] clean - no events discarded")
        return 0
    print(f"[loss] ** {totals['discarded_events']} events discarded, "
          f"{totals['lost_packets']} packets lost - RUN IS SUSPECT **")
    return 2


if __name__ == "__main__":
    sys.exit(main())
