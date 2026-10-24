#!/usr/bin/env python3
"""Figure 1: the delivery cliff. Built from E1-delivery-cliff.csv.

Two panels sharing a log-scale x axis (tool result size, in characters):
  (a) percent of the LATE field's rows that reach the model, under each bound
  (b) whether the payload is parseable at all, shown as a status strip

The synthetic sweep (25 late rows, grown by adding more short-lived
processes) and the real production trace (128 late rows, Sec. III-B) are
different datasets at different scales, so panel (a) reports percent
delivered rather than raw row counts - that is what lets both be plotted
on one axis and lets the real incident mark where it actually falls.

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
    import matplotlib.ticker as mticker
except ImportError:
    print("matplotlib not available", file=sys.stderr)
    raise SystemExit(1)

# Okabe-Ito: colourblind-safe, prints legibly in greyscale.
DEFECT, REPAIR = "#D55E00", "#0072B2"
CAP = 6000                 # the shipped flat-cut budget (V1_CAP in replay_delivery.py)
PROD_CHARS = 33370         # the real production trace's listing result (Sec. III-B)
PROD_LATE_ROWS = 128       # that trace's late-field row count


def load():
    with open(CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("n_spawned", "result_chars", "defect_late_rows", "repair_late_rows"):
            r[k] = int(r[k])
        r["defect_valid_json"] = r["defect_valid_json"] == "True"
        r["repair_valid_json"] = r["repair_valid_json"] == "True"
    return rows


def main() -> int:
    rows = load()
    x = [r["result_chars"] for r in rows]
    # Percent of the (fixed, 25-row) late field actually delivered.
    late_total = rows[0]["repair_late_rows"]  # repair always delivers all of them
    pct_d = [100.0 * r["defect_late_rows"] / late_total for r in rows]
    pct_r = [100.0 * r["repair_late_rows"] / late_total for r in rows]

    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7.5,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 200,
    })
    fig, (ax, bx) = plt.subplots(
        2, 1, figsize=(3.4, 3.15), sharex=True,
        gridspec_kw={"height_ratios": [3.2, 0.9], "hspace": 0.1})

    x_lo, x_hi = 1500, PROD_CHARS * 1.35

    # Shade the over-budget zone so the cliff reads as a region, not just a line.
    ax.axvspan(CAP, x_hi, color=DEFECT, alpha=0.07, zorder=0, lw=0)
    bx.axvspan(CAP, x_hi, color=DEFECT, alpha=0.07, zorder=0, lw=0)

    ax.grid(axis="y", color="0.88", lw=0.6, zorder=0)
    ax.plot(x, pct_r, "o-", color=REPAIR, lw=1.8, ms=4, label="row-aware bound",
             zorder=3)
    ax.plot(x, pct_d, "s-", color=DEFECT, lw=1.8, ms=4, label="prefix slice",
             zorder=3)

    # The real production trace, plotted on the same axis: it is not another
    # synthetic point, it is Sec. III-B's actual deployed-scale measurement.
    ax.plot(PROD_CHARS, 100, "*", color=REPAIR, ms=13, mec="white", mew=0.6,
            zorder=4)
    ax.plot(PROD_CHARS, 0, "*", color=DEFECT, ms=13, mec="white", mew=0.6,
            zorder=4)
    ax.annotate(
        "the real trace: 33,370 chars,\n%d records. All delivered,\nor all lost."
        % PROD_LATE_ROWS,
        xy=(PROD_CHARS, 50), xytext=(0.97, 0.50), textcoords="axes fraction",
        ha="right", va="center", fontsize=6.6, color="0.25",
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="0.75", lw=0.6))

    ax.axvline(CAP, color="0.4", lw=0.9, ls=":", zorder=1)
    ax.annotate("6,000-char cap\n(shipped)", xy=(CAP, 78),
                xytext=(CAP * 0.56, 62), fontsize=6.8, color="0.3", ha="center",
                arrowprops=dict(arrowstyle="-", color="0.5", lw=0.7))

    ax.set_xscale("log")
    ax.set_xlim(x_lo, x_hi)
    tick_vals = [2000, 4000, 6000, 10000, 20000, 33370]
    ax.xaxis.set_major_locator(mticker.FixedLocator(tick_vals))
    ax.xaxis.set_minor_locator(mticker.NullLocator())
    ax.set_ylim(-6, 112)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("% of the late field's rows\ndelivered to the model")
    ax.legend(frameon=False, loc="center left", bbox_to_anchor=(0.015, 0.30))

    # Validity as a status strip (broken_barh), not a 0/1 line plot.
    bar_h, gap = 0.38, 0.55
    for i, (label, valid_flags, color) in enumerate(
            [("prefix\nslice", [r["defect_valid_json"] for r in rows], None),
             ("row-aware\nbound", [r["repair_valid_json"] for r in rows], None)]):
        y0 = i * gap
        spans, start, cur = [], x[0], None
        edges = x + [x_hi]
        flags = valid_flags + [valid_flags[-1]]
        seg_start = x_lo if i == 1 else x_lo  # both rows start at the left edge
        prev = flags[0]
        seg_from = x_lo
        for xi, v in zip(edges, flags):
            if v != prev:
                spans.append((seg_from, xi - seg_from, prev))
                seg_from = xi
            prev = v
        spans.append((seg_from, x_hi - seg_from, prev))
        for seg_x, seg_w, valid in spans:
            c = REPAIR if valid else DEFECT
            bx.broken_barh([(seg_x, seg_w)], (y0, bar_h), facecolors=c,
                            edgecolors="white", linewidth=0.4, alpha=0.9)
    bx.set_yticks([bar_h / 2, gap + bar_h / 2])
    bx.set_yticklabels(["defect", "repair"])
    bx.set_ylim(-0.25, gap + bar_h + 0.2)
    bx.set_ylabel("payload", labelpad=2)
    bx.axvline(CAP, color="0.4", lw=0.9, ls=":", zorder=1)
    bx.set_xlabel("tool result size, characters "
                  "(grown by workload scale, not by the question asked)")
    def _fmt_k(v, _):
        k = v / 1000
        return (f"{k:.1f}k" if abs(k - round(k)) > 0.01 else f"{k:g}k") if v >= 1000 else f"{v:g}"
    bx.xaxis.set_major_formatter(mticker.FuncFormatter(_fmt_k))

    fig.tight_layout(pad=0.3)
    for ext in ("pdf", "png"):
        p = os.path.join(HERE, f"fig_cliff.{ext}")
        fig.savefig(p, bbox_inches="tight")
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
