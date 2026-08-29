#!/usr/bin/env python3
"""Write a synthetic ground_truth.json for a no-fault run, so it can be judged like any other.

A `normal` run has no injection window, so the blueprints' baseline-vs-incident comparison
has nothing to anchor on. That does not excuse the run from the test — it is the most
important negative control we have. If a blueprint fires on a healthy system with an
arbitrary window boundary, the blueprint is broken.

So we cut the trace at an arbitrary interior point and declare everything after it the
"incident". The correct answer for every such run is: neither blueprint fires.

The window is taken from the trace's own first event, not from wall-clock, so it lands
inside the recorded region regardless of when the run happened.

    python3 synthesize_gt.py --ctf <ctf_dir> --out <ctf_parent>/ground_truth.json
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")
TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")


def first_timestamp(ctf):
    """Read the trace until the first event that carries a timestamp. Cheap: we stop at once."""
    p = subprocess.Popen([BT2, ctf], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, errors="replace", env={**os.environ, "TZ": "UTC"})
    try:
        for line in p.stdout:
            m = TS.match(line)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    finally:
        try:
            p.terminate()
        except Exception:                                              # noqa: BLE001
            pass
    return None


def hms(v):
    v %= 86400
    return f"{v // 3600:02d}:{(v % 3600) // 60:02d}:{v % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--offset-s", type=int, default=90,
                    help="seconds into the trace where the pseudo-incident starts. Must leave "
                         "room for the 55s baseline the analysis reads before it.")
    ap.add_argument("--length-s", type=int, default=120)
    a = ap.parse_args()

    t0 = first_timestamp(a.ctf)
    if t0 is None:
        sys.exit(f"could not read any timestamped event from {a.ctf}")

    start, end = t0 + a.offset_s, t0 + a.offset_s + a.length_s
    gt = {
        "fault": {
            "recipe": "none",
            "synthetic_window": True,
            "note": "NO FAULT WAS INJECTED. This window is an arbitrary cut of a healthy run, "
                    "used as a negative control: the correct outcome is that no blueprint fires.",
            "injection_start_utc": f"1970-01-01T{hms(start)}Z",
            "injection_end_utc": f"1970-01-01T{hms(end)}Z",
            "target_service": None,
        }
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(gt, open(a.out, "w"), indent=2)
    print(f"synthetic window {hms(start)} -> {hms(end)} (trace starts {hms(t0)}) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
