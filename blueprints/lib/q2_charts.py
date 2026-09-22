#!/usr/bin/env python3
"""Four charts for the Sock Shop results.

Four, not fourteen. Each answers a different question, and none repeats another:

  1  effect heatmap   where does the blueprint help, and where does it hurt?
  2  dumbbell         how good is it, with and without, grouped by fault scope
  3  ceiling-floor    WHY the effect is zero on some problems - no room, or stuck
  4  cost             what the blueprint costs in time and tokens

Colour is assigned by the job it does, and the palettes were run through the
validator rather than eyeballed:

  heatmap    diverging - blue/red poles, neutral GREY midpoint. Polarity: helps vs hurts.
             Never a rainbow, and never a hue at the midpoint, or "no change" reads as a value.
  the rest   categorical - slot 1 blue, slot 2 orange. 2 slots, worst-pair CVD dE 24.7.
  scatter    3 slots (blue, orange, aqua), all-pairs CVD dE 9.2. Aqua sits below 3:1 on the
             light surface, so every point carries a visible label - that is the relief rule,
             not decoration.

    python q2_charts.py --out-dir <dir>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import q2_harness as Q      # noqa: E402
import q2_rescore as RS     # noqa: E402

# --- design tokens, from the validated reference palette ------------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8a8985"
GRID = "#e6e5e1"
S1 = "#2a78d6"   # categorical slot 1 - blue
S2 = "#eb6834"   # categorical slot 2 - orange
S3 = "#1baf7a"   # categorical slot 3 - aqua
DIV_NEG = "#d03b3b"
DIV_MID = "#f0efec"
DIV_POS = "#2a78d6"

DIVERGING = LinearSegmentedColormap.from_list("helps", [DIV_NEG, DIV_MID, DIV_POS])

# Problems grouped by what the fault actually touches. This is the split the results fall
# along, so it is the split the charts are built on rather than alphabetical order.
BUCKETS = [
    ("Whole host", ["anomaly_cpu", "anomaly_net", "noisy_neighbor"], S1),
    ("A datastore", ["slow_db"], S2),
    ("One service", ["svc_cpu_cap", "svc_net"], S3),
]
ORDER = [p for _, ps, _ in BUCKETS for p in ps]
BUCKET_OF = {p: b for b, ps, _ in BUCKETS for p in ps}
COLOR_OF = {p: c for _, ps, c in BUCKETS for p in ps}

METRICS = [
    ("where_ok", "Found\nthe place"),
    ("window_hit", "Found\nthe time"),
    ("described", "Explained\nthe problem"),
    ("both_ok", "Both\nright"),
]


def load(out_dir):
    rows = []
    for sp in sorted(glob.glob(os.path.join(out_dir, "*", "*", "*", "*", "*", "score.json"))):
        try:
            r = json.load(open(sp, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rp = os.path.join(os.path.dirname(sp), "rescored.json")
        r["_v2"] = {}
        if os.path.exists(rp):
            try:
                r["_v2"] = json.load(open(rp, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        rows.append(r)
    return rows


def metric(rs, key, prob):
    """One metric for a set of runs, as a fraction 0..1."""
    if not rs:
        return None
    if key == "where_ok":
        return sum(1 for r in rs if RS.where_ok(r.get("where", ""), prob)) / len(rs)
    if key == "window_hit":
        return sum(1 for r in rs if r.get("window_verdict") == "hit") / len(rs)
    if key == "both_ok":
        return sum(1 for r in rs if r.get("both_ok")) / len(rs)
    if key == "described":
        v = [r["_v2"].get("what_score_v2") for r in rs
             if isinstance(r["_v2"].get("what_score_v2"), (int, float))]
        return (sum(v) / len(v)) if v else None
    if key == "tokens":
        v = sorted(r.get("tokens") or 0 for r in rs)
        return v[len(v) // 2]
    if key == "seconds":
        v = sorted(r.get("seconds") or 0 for r in rs)
        return v[len(v) // 2]
    return None


def arm(rows, prob, which):
    return [r for r in rows if r.get("problem") == prob and r.get("arm") == which]


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0, labelsize=9)


# --- 1. where does the blueprint help? ------------------------------------------------------
def chart_effect(rows, path):
    fig, ax = plt.subplots(figsize=(8.2, 4.6), facecolor=SURFACE)
    data = []
    for prob in ORDER:
        row = []
        for key, _ in METRICS:
            a = metric(arm(rows, prob, "none"), key, prob)
            b = metric(arm(rows, prob, "given"), key, prob)
            row.append(None if (a is None or b is None) else 100 * (b - a))
        data.append(row)

    lim = 60
    ax.imshow([[0 if v is None else v for v in r] for r in data],
              cmap=DIVERGING, vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(METRICS)))
    ax.set_xticklabels([m[1] for m in METRICS], fontsize=9.5, color=INK_2)
    ax.set_yticks(range(len(ORDER)))
    ax.set_yticklabels(ORDER, fontsize=10, color=INK)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)

    # 2px surface gap between cells - the spacer rule, so adjacent fills never bleed together
    for i in range(len(ORDER) + 1):
        ax.axhline(i - 0.5, color=SURFACE, lw=2)
    for j in range(len(METRICS) + 1):
        ax.axvline(j - 0.5, color=SURFACE, lw=2)

    # every cell direct-labelled: the number is the point, and it also keeps the chart
    # readable for anyone who cannot separate the two poles by hue
    for i, r in enumerate(data):
        for j, v in enumerate(r):
            if v is None:
                continue
            ink = "#ffffff" if abs(v) > 34 else INK
            ax.text(j, i, "%+d" % round(v), ha="center", va="center",
                    fontsize=11, color=ink, fontweight="bold")

    # which bucket each problem belongs to, so the grouping is visible without a second chart
    prev = None
    for i, prob in enumerate(ORDER):
        b = BUCKET_OF[prob]
        if b != prev:
            ax.text(-0.98, i - 0.42, b.upper(), fontsize=7.5, color=INK_MUTED,
                    ha="left", va="center", fontweight="bold")
            prev = b

    ax.set_title("Does the blueprint help?", fontsize=14, color=INK,
                 fontweight="bold", pad=26, loc="left")
    ax.text(0, 1.10, "Change in percentage points when the agent is given the blueprint. "
                     "Blue is better, red is worse.",
            transform=ax.transAxes, fontsize=9.5, color=INK_2, va="bottom")
    fig.text(0.013, 0.015,
             "Ignore a big number under 'both right' on its own - the blueprint text names the "
             "fault, so it can be read straight off.",
             fontsize=8, color=INK_MUTED)
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 2. how good is it, with and without? ---------------------------------------------------
def chart_dumbbell(rows, path):
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.4), facecolor=SURFACE, sharey=True)
    for ax, (key, label) in zip(axes, [METRICS[0], METRICS[1]]):
        style(ax)
        ax.set_facecolor(SURFACE)
        ys = list(range(len(ORDER)))[::-1]
        for y, prob in zip(ys, ORDER):
            a = metric(arm(rows, prob, "none"), key, prob)
            b = metric(arm(rows, prob, "given"), key, prob)
            if a is None or b is None:
                continue
            a, b = 100 * a, 100 * b
            ax.plot([a, b], [y, y], color=GRID, lw=2.5, zorder=1, solid_capstyle="round")
            ax.scatter([a], [y], s=95, color=S1, zorder=3,
                       edgecolors=SURFACE, linewidths=2)   # 2px surface ring
            ax.scatter([b], [y], s=95, color=S2, zorder=3,
                       edgecolors=SURFACE, linewidths=2)
            far, near = (b, a) if b >= a else (a, b)
            ax.text(far + 3.2, y, "%d%%" % round(far), va="center", fontsize=9, color=INK)
            if abs(b - a) > 6:
                ax.text(near - 3.2, y, "%d%%" % round(near), va="center", ha="right",
                        fontsize=9, color=INK_MUTED)
        ax.set_xlim(-14, 118)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels(["0", "25", "50", "75", "100%"])
        ax.set_yticks(ys)
        ax.set_yticklabels(ORDER, fontsize=10, color=INK)
        ax.xaxis.grid(True, color=GRID, lw=1)
        ax.set_axisbelow(True)
        ax.set_title(label.replace("\n", " "), fontsize=11.5, color=INK,
                     fontweight="bold", loc="left", pad=8)

    h = [plt.Line2D([], [], marker="o", ls="", ms=9, color=S1, label="without blueprint"),
         plt.Line2D([], [], marker="o", ls="", ms=9, color=S2, label="with blueprint")]
    axes[0].legend(handles=h, loc="upper left", bbox_to_anchor=(0, -0.13), ncol=2,
                   frameon=False, fontsize=9.5, labelcolor=INK_2)
    fig.suptitle("How often does it get the answer right?", fontsize=14, color=INK,
                 fontweight="bold", x=0.013, ha="left", y=0.985)
    fig.text(0.013, 0.905, "30 runs behind each dot. Problems grouped by what the fault "
                           "touches: whole host, then a datastore, then one service.",
             fontsize=9.5, color=INK_2)
    fig.tight_layout(rect=(0, 0.06, 1, 0.88))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 3. why the effect is zero in places -----------------------------------------------------
def chart_ceiling(rows, path):
    fig, ax = plt.subplots(figsize=(6.8, 6.1), facecolor=SURFACE)
    style(ax)
    ax.plot([-5, 105], [-5, 105], color=GRID, lw=2, zorder=1)
    ax.fill_between([-5, 105], [-5, 105], 112, color=S1, alpha=0.05, zorder=0)

    for prob in ORDER:
        a = metric(arm(rows, prob, "none"), "where_ok", prob)
        b = metric(arm(rows, prob, "given"), "where_ok", prob)
        if a is None or b is None:
            continue
        a, b = 100 * a, 100 * b
        ax.scatter([a], [b], s=190, color=COLOR_OF[prob], zorder=3,
                   edgecolors=SURFACE, linewidths=2)
        dy = 6 if b < 92 else -9
        ax.annotate(prob, (a, b), textcoords="offset points", xytext=(0, dy),
                    ha="center", fontsize=9.5, color=INK)

    ax.text(52, 103, "blueprint helped", fontsize=9.5, color=S1, ha="center",
            fontweight="bold")
    ax.text(88, 78, "no change", fontsize=9, color=INK_MUTED, rotation=38, ha="center")
    ax.annotate("already at the ceiling\nnothing left to gain", (100, 100),
                textcoords="offset points", xytext=(-20, -46), ha="right",
                fontsize=8.5, color=INK_MUTED)
    ax.annotate("stuck at the floor\nthe tools could not\ntell containers apart", (0, 0),
                textcoords="offset points", xytext=(16, 22), ha="left",
                fontsize=8.5, color=INK_MUTED)

    ax.set_xlim(-5, 112)
    ax.set_ylim(-5, 112)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25", "50", "75", "100%"])
    ax.set_yticklabels(["0", "25", "50", "75", "100%"])
    ax.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.set_xlabel("found the place WITHOUT a blueprint", fontsize=10, color=INK_2)
    ax.set_ylabel("found the place WITH a blueprint", fontsize=10, color=INK_2)
    ax.set_title("Where there was room to improve", fontsize=14, color=INK,
                 fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.055, "Above the line, the blueprint helped. On it, it changed nothing - and "
                      "the reason differs at each end.",
            transform=ax.transAxes, fontsize=9.5, color=INK_2, va="bottom")
    h = [plt.Line2D([], [], marker="o", ls="", ms=9, color=c, label=b)
         for b, _, c in BUCKETS]
    ax.legend(handles=h, loc="lower right", frameon=False, fontsize=9.5,
              labelcolor=INK_2, title="fault touches", title_fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 4. what it costs ------------------------------------------------------------------------
def chart_cost(rows, path):
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.9), facecolor=SURFACE, sharey=True)
    for ax, (key, label, fmt, scale) in zip(
            axes, [("seconds", "Time per run (minutes)", "%.1f", 1 / 60.0),
                   ("tokens", "Tokens per run (thousands)", "%.0f", 1 / 1000.0)]):
        style(ax)
        ys = list(range(len(ORDER)))[::-1]
        for y, prob in zip(ys, ORDER):
            a = metric(arm(rows, prob, "none"), key, prob)
            b = metric(arm(rows, prob, "given"), key, prob)
            if a is None or b is None:
                continue
            a, b = a * scale, b * scale
            ax.plot([a, b], [y, y], color=GRID, lw=2.5, zorder=1, solid_capstyle="round")
            ax.scatter([a], [y], s=85, color=S1, zorder=3, edgecolors=SURFACE, linewidths=2)
            ax.scatter([b], [y], s=85, color=S2, zorder=3, edgecolors=SURFACE, linewidths=2)
            hi = max(a, b)
            ax.text(hi * 1.04, y, fmt % hi, va="center", fontsize=9, color=INK)
        ax.set_yticks(ys)
        ax.set_yticklabels(ORDER, fontsize=10, color=INK)
        ax.xaxis.grid(True, color=GRID, lw=1)
        ax.set_axisbelow(True)
        ax.set_xlim(0, None)
        ax.margins(x=0.18)
        ax.set_title(label, fontsize=11.5, color=INK, fontweight="bold", loc="left", pad=8)

    h = [plt.Line2D([], [], marker="o", ls="", ms=9, color=S1, label="without blueprint"),
         plt.Line2D([], [], marker="o", ls="", ms=9, color=S2, label="with blueprint")]
    axes[0].legend(handles=h, loc="upper left", bbox_to_anchor=(0, -0.15), ncol=2,
                   frameon=False, fontsize=9.5, labelcolor=INK_2)
    fig.suptitle("What the blueprint costs", fontsize=14, color=INK, fontweight="bold",
                 x=0.013, ha="left", y=0.985)
    fig.text(0.013, 0.885, "Middle value of 30 runs. The blueprint adds tokens because it is "
                           "long, but it does not make the agent slower.",
             fontsize=9.5, color=INK_2)
    fig.tight_layout(rect=(0, 0.07, 1, 0.86))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", default="/scratch/yuvraj17/stratatrace/results/q2-full")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()

    rows = load(a.full)
    if not rows:
        print("no runs under %s" % a.full)
        return 1
    os.makedirs(a.out_dir, exist_ok=True)
    made = [
        chart_effect(rows, os.path.join(a.out_dir, "1-blueprint-effect.png")),
        chart_dumbbell(rows, os.path.join(a.out_dir, "2-accuracy.png")),
        chart_ceiling(rows, os.path.join(a.out_dir, "3-room-to-improve.png")),
        chart_cost(rows, os.path.join(a.out_dir, "4-cost.png")),
    ]
    for m in made:
        print("wrote %s  (%d KB)" % (m, os.path.getsize(m) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
