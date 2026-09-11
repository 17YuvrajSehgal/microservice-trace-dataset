"""Draw one card per blueprint, each on a run of the fault that blueprint is for.

    python3 blueprints/lib/make_cards.py --packs <dir> --ruler blueprints/results/ruler.json

Writes into each problem's own folder, so the picture sits beside the blueprint that
claims it: blueprints/problems/<id>/evidence/<id>_card.svg
"""
import argparse
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_card as BC  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--ruler", required=True)
    ap.add_argument("--problems", default="blueprints/problems")
    ap.add_argument("--only", default="", help="one blueprint id, for iterating")
    a = ap.parse_args()

    ruler = json.load(io.open(a.ruler, encoding="utf-8"))
    packs = {}
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if p.get("run_id"):
            fam = p.get("family_dir") or ""
            packs.setdefault(fam[3:] if fam.startswith("tt_") else fam, []).append(p)

    made, missing = [], []
    for bid, cfg in sorted(BC.CARDS.items()):
        if a.only and bid != a.only:
            continue
        pick = None
        for fam in cfg["owns"]:
            if packs.get(fam):
                pick = sorted(packs[fam], key=lambda p: p["run_id"])[0]
                break
        if not pick:
            missing.append((bid, ", ".join(cfg["owns"])))
            continue
        out_dir = os.path.join(a.problems, bid, "evidence")
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        out = os.path.join(out_dir, bid + "_card.svg")
        svg = BC.build(pick, ruler, bid, a.problems)
        with io.open(out, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(svg)
        made.append((bid, pick["run_id"], len(svg)))

    for bid, run, n in made:
        print("  %-28s %-44s %6d bytes" % (bid, run, n))
    for bid, fams in missing:
        print("  SKIPPED %-24s no pack for family: %s" % (bid, fams))
    print("%d cards written, %d skipped" % (len(made), len(missing)))


if __name__ == "__main__":
    main()
