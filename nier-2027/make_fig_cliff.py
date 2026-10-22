#!/usr/bin/env python3
"""Figure 1: the delivery cliff. Built from E1-delivery-cliff.csv.

Two panels sharing an x axis (how many short-lived processes the trace holds,
which is a property of the workload and not of the question):
  (a) rows of the LATE field that reach the model, under each bound
  (b) whether the payload is parseable at all

    python nier-2027/make_fig_cliff.py            # writes fig_cliff.pdf + .png
"""
from __future__ import annotations
import csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "E1-delivery-cliff.csv")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not available", file=sys.stderr)
    raise SystemExit(1)

# Okabe-Ito: colourblind-safe, prints legibly in greyscale.
DEFECT, REPAIR = "#D55E00", "#0072B2"


def load():
    with open(CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    rows = load()
    x = [int(r["n_spawned"]) for r in rows]
    late_d = [int(r["defect_late_rows"]) for r in rows]
    late_r = [int(r["repair_late_rows"]) for r in rows]
    val_d = [r["defect_valid_json"] == "True" for r in rows]
    val_r = [r["repair_valid_json"] == "True" for r in rows]

    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7.5,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 200,
    })
    fig, (ax, bx) = plt.subplots(
        2, 1, figsize=(3.4, 2.9), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.18})

    ax.plot(x, late_r, "o-", color=REPAIR, lw=1.6, ms=3.5,
            label="row-aware bound")
    ax.plot(x, late_d, "s-", color=DEFECT, lw=1.6, ms=3.5,
            label="prefix slice")
    cliff = next((xi for xi, v in zip(x, late_d) if v == 0), None)
    if cliff is not None:
        ax.axvline(cliff, color="0.6", lw=0.8, ls=":", zorder=0)
        ax.annotate("result crosses\nthe bound", xy=(cliff, max(late_r) * 0.55),
                    xytext=(cliff * 1.12, max(late_r) * 0.62), color="0.35",
                    fontsize=7, ha="left",
                    arrowprops=dict(arrowstyle="-", color="0.6", lw=0.8))
    ax.set_ylabel("rows of the late field\ndelivered to the model")
    ax.set_ylim(-1.5, max(late_r) + 2)
    ax.legend(frameon=False, loc="center left")

    bx.plot(x, [1 if v else 0 for v in val_r], "o-", color=REPAIR, lw=1.6, ms=3.5)
    bx.plot(x, [1 if v else 0 for v in val_d], "s-", color=DEFECT, lw=1.6, ms=3.5)
    bx.set_yticks([0, 1]); bx.set_yticklabels(["invalid", "valid"])
    bx.set_ylim(-0.4, 1.4)
    bx.set_ylabel("payload", labelpad=2)
    bx.set_xlabel("short-lived processes in the trace "
                  "(a property of the workload, not the question)")

    fig.tight_layout(pad=0.3)
    for ext in ("pdf", "png"):
        p = os.path.join(HERE, f"fig_cliff.{ext}")
        fig.savefig(p, bbox_inches="tight")
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
