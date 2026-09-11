"""Measure where EVERY fault family sits on each blueprint's deciding number.

A blueprint claims one number separates its fault from everything else. That claim is only
checkable if you know where everything else sits. We have 273 packs covering 27 families on
two applications, so we can put them all on one axis and look.

The output feeds `blueprint_card.py`, which draws that axis. Nothing here decides anything -
it reads the SAME extractors the rules use (`blueprint_decide._cpu` and friends), so the
number on the picture is the number the rule saw. Re-deriving it here would let the picture
drift away from the decision, which is the one thing a picture like this must never do.

Run on the cluster, where the packs are:

    python3 blueprints/lib/build_ruler.py \
        --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
        --out blueprints/results/ruler.json
"""
import argparse
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD  # noqa: E402


def _proc(pack, key):
    return ((pack.get("process") or {}).get("signature") or {}).get(key)


# Each entry: how to pull the number a rule decides on, straight out of the pack.
# `label` and `unit` are what a reader sees; keep them plain.
SIGNALS = {
    "host_util_incident": {
        "label": "host CPU at the busiest point",
        "unit": "share of all cores",
        "get": lambda p: BD._cpu(p)["util_incident"],
    },
    "thief_cores": {
        "label": "cores taken by a process that was not using them before",
        "unit": "cores",
        "get": lambda p: BD._cpu(p)["thief_cores"],
    },
    "util_ratio": {
        "label": "host CPU during the fault, against its own baseline",
        "unit": "x baseline",
        "get": lambda p: BD._cpu(p)["util_ratio"],
    },
    "iops_per_irq": {
        "label": "disk requests gained per unit of interrupt rise",
        "unit": "requests/s per x",
        "get": lambda p: BD._io(p)["iops_per_irq"],
    },
    "hardirq_x": {
        "label": "time spent handling device interrupts",
        "unit": "x baseline",
        "get": lambda p: BD._io(p)["hardirq_x"],
    },
    "worst_retrans_pct": {
        "label": "segments the network had to send again",
        "unit": "%",
        "get": lambda p: BD._net(p)["worst_retrans_pct"],
    },
    "socket_block_x": {
        "label": "longest wait in a socket call",
        "unit": "x baseline",
        "get": lambda p: BD._blk(p)["max_socket_x"] or None,
    },
    "fork_newcomer_per_s": {
        "label": "processes per second started by a newly busy program",
        "unit": "per second",
        "get": lambda p: _proc(p, "fork_newcomer_per_s"),
    },
    "tx_newcomer_bytes_per_s": {
        "label": "bytes per second sent by a newly busy program",
        "unit": "bytes/s",
        "get": lambda p: _proc(p, "tx_newcomer_bytes_per_s"),
    },
    "emfile_per_s": {
        "label": "calls per second refused for want of a file descriptor",
        "unit": "per second",
        "get": lambda p: _proc(p, "emfile_per_s_incident"),
    },
}


def family_of(pack):
    """Family name without the Train Ticket prefix, so both apps land on the same label."""
    fam = pack.get("family_dir") or ""
    return fam[3:] if fam.startswith("tt_") else fam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True, help="directory of pack .json files")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.packs, "*.json")))
    out = {"n_packs": 0, "source": a.packs, "signals": {}}
    for key, spec in SIGNALS.items():
        out["signals"][key] = {"label": spec["label"], "unit": spec["unit"], "points": []}

    skipped = []
    for f in files:
        try:
            pack = json.load(io.open(f, encoding="utf-8"))
        except Exception as e:                                   # a half-written pack
            skipped.append((os.path.basename(f), type(e).__name__))
            continue
        if not pack.get("run_id"):
            skipped.append((os.path.basename(f), "no run_id"))
            continue
        out["n_packs"] += 1
        row = {"app": pack.get("app"), "family": family_of(pack), "run": pack["run_id"]}
        for key, spec in SIGNALS.items():
            try:
                v = spec["get"](pack)
            except Exception:
                v = None
            if v is None:
                continue
            out["signals"][key]["points"].append(dict(row, v=round(float(v), 4)))

    out["skipped"] = skipped
    with io.open(a.out, "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(json.dumps(out, indent=1) + chr(10))

    print("packs read: %d   skipped: %d" % (out["n_packs"], len(skipped)))
    for key, s in out["signals"].items():
        fams = len(set((p["app"], p["family"]) for p in s["points"]))
        print("  %-26s %4d runs  %3d family/app groups" % (key, len(s["points"]), fams))
    print("wrote " + a.out)


if __name__ == "__main__":
    main()
