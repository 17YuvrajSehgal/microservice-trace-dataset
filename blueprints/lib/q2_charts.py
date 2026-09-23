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
import random
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

    # Title and subtitle both in FIGURE coords. An axes title and an axes-relative subtitle
    # move independently, and the render pass showed them printed on top of each other.
    fig.text(0.013, 0.958, "Does the blueprint help?", fontsize=14, color=INK,
             fontweight="bold", va="top")
    fig.text(0.013, 0.888, "Change in percentage points when the agent is given the "
                           "blueprint. Blue is better, red is worse.",
             fontsize=9.5, color=INK_2, va="top")
    fig.text(0.013, 0.018,
             "Ignore a big number under 'both right' on its own - the blueprint text names "
             "the fault, so it can be read straight off.",
             fontsize=8, color=INK_MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 0.85))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 3. why the effect is zero in places -----------------------------------------------------
def chart_ceiling(rows, path):
    fig, ax = plt.subplots(figsize=(6.8, 6.1), facecolor=SURFACE)
    style(ax)
    ax.plot([-5, 105], [-5, 105], color=GRID, lw=2, zorder=1)
    ax.fill_between([-5, 105], [-5, 105], 112, color=S1, alpha=0.05, zorder=0)

    # Coincident points get ONE marker and a combined label. svc_net and svc_cpu_cap both sit
    # at (0, 0), and the render pass showed their two labels printed on top of each other.
    at = {}
    for prob in ORDER:
        a = metric(arm(rows, prob, "none"), "where_ok", prob)
        b = metric(arm(rows, prob, "given"), "where_ok", prob)
        if a is None or b is None:
            continue
        at.setdefault((round(100 * a), round(100 * b)), []).append(prob)

    # Hand-placed offsets. These four points sit close enough that automatic placement runs
    # labels into the diagonal or into each other.
    NUDGE = {"anomaly_cpu": (-12, 12), "anomaly_net": (-8, 13), "noisy_neighbor": (-12, -6),
             "slow_db": (0, 14), "svc_net": (14, 2), "svc_cpu_cap": (14, 2)}
    for (a, b), probs in sorted(at.items()):
        ax.scatter([a], [b], s=190, color=COLOR_OF[probs[0]], zorder=3,
                   edgecolors=SURFACE, linewidths=2)
        label = probs[0] if len(probs) == 1 else " + ".join(sorted(probs))
        dx, dy = NUDGE.get(probs[0], (0, 13))
        ha = "left" if dx > 4 else ("right" if dx < -4 else "center")
        ax.annotate(label, (a, b), textcoords="offset points", xytext=(dx, dy),
                    ha=ha, fontsize=9.5, color=INK)

    ax.text(27, 86, "blueprint helped", fontsize=10, color=S1, ha="center",
            fontweight="bold")
    ax.text(76, 64, "no change", fontsize=9, color=INK_MUTED, rotation=41, ha="center")
    ax.annotate("already at the ceiling -" + chr(10) + "nothing left to gain", (100, 100),
                textcoords="offset points", xytext=(-6, -30), ha="right",
                fontsize=8.5, color=INK_MUTED)
    ax.annotate("stuck at the floor - the tools" + chr(10) + "could not tell containers apart",
                (0, 0), textcoords="offset points", xytext=(16, 34), ha="left",
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
    fig.text(0.012, 0.972, "Where there was room to improve", fontsize=14, color=INK,
             fontweight="bold", va="top")
    fig.text(0.012, 0.927, "Above the line the blueprint helped. On the line it changed"
                           " nothing -" + chr(10) + "and the reason differs at each end.",
             fontsize=9.5, color=INK_2, va="top", linespacing=1.4)
    h = [plt.Line2D([], [], marker="o", ls="", ms=9, color=c, label=b)
         for b, _, c in BUCKETS]
    ax.legend(handles=h, loc="lower right", frameon=False, fontsize=9.5,
              labelcolor=INK_2, title="fault touches", title_fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.885))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 2. every single run, one square ---------------------------------------------------------
# Ordinal ramp: one hue, monotone lightness, validated with --ordinal. The outcome is ordered
# best to worst, so an ordered encoding is the honest one - a categorical set of hues would
# imply the four outcomes are unrelated kinds rather than degrees of the same thing.
OUT_COLORS = [
    ("named", "#184f95", "named the thing"),
    ("container", "#256abf", "named one container"),
    ("scope", "#3987e5", "said host only"),
    ("ambiguous", "#86b6ef", "said a shared runtime"),
    ("wrong", "#e6e5e1", "wrong"),
]
OUT_INK = {"named": "#184f95", "container": "#256abf", "scope": "#3987e5",
           "ambiguous": "#86b6ef", "wrong": "#e6e5e1", "none": "#e6e5e1"}
ARM_COLS = [("nohint", "none", "no hint\nno blueprint"),
            ("nohint", "given", "no hint\nblueprint"),
            ("hint", "none", "hint\nno blueprint"),
            ("hint", "given", "hint\nblueprint")]


def chart_every_run(rows, path):
    """All 360 runs, one square each. Nothing averaged.

    A summary rate cannot tell a stable 3-of-5 from a 5-of-5 on one incident and 0-of-5 on the
    next, and those are very different findings. Here every repeat is visible, so consistency
    is something you SEE rather than something you take on trust.
    """
    BW, BH, GAPX, GAPY = 5, 3, 1.5, 1.4          # 5 repeats wide, 3 incidents tall
    fig, ax = plt.subplots(figsize=(11.6, 7.4), facecolor=SURFACE)

    incid = {}
    for prob in ORDER:
        seen = []
        for r in rows:
            if r.get("problem") == prob and r.get("run_id") not in seen:
                seen.append(r.get("run_id"))
        incid[prob] = sorted(seen)

    for pi, prob in enumerate(ORDER):
        y0 = (len(ORDER) - 1 - pi) * (BH + GAPY)
        for ai, (ask, armv, _) in enumerate(ARM_COLS):
            x0 = ai * (BW + GAPX)
            for r in rows:
                if r.get("problem") != prob or r.get("ask") != ask or r.get("arm") != armv:
                    continue
                try:
                    row_i = incid[prob].index(r.get("run_id"))
                    col_i = int(r.get("repeat", 1)) - 1
                except (ValueError, TypeError):
                    continue
                c = OUT_INK.get(r.get("where") or "wrong", "#e6e5e1")
                ax.add_patch(plt.Rectangle(
                    (x0 + col_i + 0.06, y0 + (BH - 1 - row_i) + 0.06), 0.88, 0.88,
                    facecolor=c, edgecolor=SURFACE, linewidth=1.4))
        ax.text(-0.7, y0 + BH / 2.0, prob, ha="right", va="center", fontsize=10.5, color=INK)

    for ai, (_, _, label) in enumerate(ARM_COLS):
        ax.text(ai * (BW + GAPX) + BW / 2.0, len(ORDER) * (BH + GAPY) - GAPY + 0.35,
                label, ha="center", va="bottom", fontsize=9.5, color=INK_2,
                linespacing=1.35)

    ax.set_xlim(-7.4, 4 * (BW + GAPX) - GAPX + 0.4)
    ax.set_ylim(-1.9, len(ORDER) * (BH + GAPY) + 1.1)
    ax.set_aspect("equal")
    ax.axis("off")

    h = [plt.Rectangle((0, 0), 1, 1, facecolor=c, edgecolor=SURFACE)
         for _, c, _ in OUT_COLORS]
    ax.legend(h, [lbl for _, _, lbl in OUT_COLORS], loc="upper left",
              bbox_to_anchor=(0.0, -0.005), ncol=5, frameon=False, fontsize=9,
              labelcolor=INK_2, handlelength=1.1, columnspacing=1.3)

    fig.text(0.012, 0.972, "Every one of the 360 runs", fontsize=14, color=INK,
             fontweight="bold", va="top")
    fig.text(0.012, 0.928, "One square per run. Each block is 5 repeats across "
                           "(left to right) by 3 incidents down. Nothing is averaged.",
             fontsize=9.5, color=INK_2, va="top")
    fig.tight_layout(rect=(0, 0.045, 1, 0.905))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 3. the window score every run actually got ----------------------------------------------
def chart_window_raw(rows, path):
    """All 360 window scores, not the hit rate.

    The tables count a "hit" at 0.5 overlap or better, which turns a continuous measurement
    into a coin flip and hides two very different failures: a near miss at 0.45 and a wild
    guess at 0.02 both read as "not a hit". The raw values show which one actually happened.
    """
    fig, ax = plt.subplots(figsize=(11.2, 5.0), facecolor=SURFACE)
    style(ax)
    rng = random.Random(7)          # fixed seed: the jitter must not move between renders

    for pi, prob in enumerate(ORDER):
        for ai, armv in enumerate(("none", "given")):
            base = pi * 2.6 + ai * 0.95
            rs = [r for r in rows if r.get("problem") == prob and r.get("arm") == armv]
            vals = [r.get("window_iou") for r in rs
                    if isinstance(r.get("window_iou"), (int, float))]
            absts = sum(1 for r in rs if r.get("window_verdict") == "abstained")
            col = S1 if armv == "none" else S2
            for v in vals:
                ax.scatter([base + rng.uniform(-0.26, 0.26)], [v], s=26, color=col,
                           alpha=0.55, linewidths=0, zorder=3)
            if vals:
                m = sorted(vals)[len(vals) // 2]
                ax.plot([base - 0.36, base + 0.36], [m, m], color=col, lw=2.6,
                        solid_capstyle="round", zorder=4)
            if absts:
                ax.text(base, -0.115, "%d" % absts, ha="center", va="center",
                        fontsize=8.5, color=INK_MUTED)

    ax.axhline(0.5, color=INK_MUTED, lw=1.4, ls=(0, (5, 4)), zorder=2)
    ax.text(-1.15, 0.52, "counted as a hit", fontsize=8.5, color=INK_MUTED, va="bottom")
    ax.text(-1.15, -0.115, "said\nunknown", fontsize=8, color=INK_MUTED, va="center",
            ha="left", linespacing=1.3)

    ax.set_xticks([pi * 2.6 + 0.47 for pi in range(len(ORDER))])
    ax.set_xticklabels(ORDER, fontsize=10, color=INK)
    ax.set_xlim(-1.3, (len(ORDER) - 1) * 2.6 + 1.5)
    ax.set_ylim(-0.17, 1.06)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "0.25", "0.5", "0.75", "1.0"])
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.set_ylabel("overlap with the real window", fontsize=10, color=INK_2)

    h = [plt.Line2D([], [], marker="o", ls="", ms=8, color=S1, label="without blueprint"),
         plt.Line2D([], [], marker="o", ls="", ms=8, color=S2, label="with blueprint"),
         plt.Line2D([], [], color=INK_MUTED, lw=2.6, label="median")]
    ax.legend(handles=h, loc="upper left", bbox_to_anchor=(0, -0.10), ncol=3,
              frameon=False, fontsize=9.5, labelcolor=INK_2)

    fig.text(0.012, 0.972, "How close was the time it gave?", fontsize=14, color=INK,
             fontweight="bold", va="top")
    fig.text(0.012, 0.928, "One dot per run, all 360. The tables count a hit at 0.5 and above, "
                           "which hides the difference between a near miss and a wild guess.",
             fontsize=9.5, color=INK_2, va="top")
    fig.tight_layout(rect=(0, 0.075, 1, 0.905))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


# --- 5. what every run cost ------------------------------------------------------------------
def chart_cost_raw(rows, path):
    """All 360 runs on the cost axes, so the spread is visible rather than a median dot."""
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.3), facecolor=SURFACE)
    rng = random.Random(11)

    ax = axes[0]
    style(ax)
    for armv, col in (("none", S1), ("given", S2)):
        xs = [(r.get("seconds") or 0) / 60.0 for r in rows if r.get("arm") == armv]
        ys = [(r.get("tokens") or 0) / 1000.0 for r in rows if r.get("arm") == armv]
        ax.scatter(xs, ys, s=22, color=col, alpha=0.45, linewidths=0)
    ax.set_xlabel("minutes", fontsize=10, color=INK_2)
    ax.set_ylabel("thousand tokens", fontsize=10, color=INK_2)
    ax.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.set_title("Every run, cost against time", fontsize=11.5, color=INK,
                 fontweight="bold", loc="left", pad=8)

    ax = axes[1]
    style(ax)
    for pi, prob in enumerate(ORDER):
        for ai, armv in enumerate(("none", "given")):
            base = pi * 2.4 + ai * 0.9
            col = S1 if armv == "none" else S2
            vals = [(r.get("seconds") or 0) / 60.0
                    for r in rows if r.get("problem") == prob and r.get("arm") == armv]
            for v in vals:
                ax.scatter([base + rng.uniform(-0.24, 0.24)], [v], s=20, color=col,
                           alpha=0.45, linewidths=0, zorder=3)
            if vals:
                m = sorted(vals)[len(vals) // 2]
                ax.plot([base - 0.33, base + 0.33], [m, m], color=col, lw=2.4,
                        solid_capstyle="round", zorder=4)
    ax.set_xticks([pi * 2.4 + 0.45 for pi in range(len(ORDER))])
    ax.set_xticklabels([p.replace("_", "\n") for p in ORDER], fontsize=8.5, color=INK)
    ax.set_ylabel("minutes per run", fontsize=10, color=INK_2)
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.set_title("Time per run, by problem", fontsize=11.5, color=INK,
                 fontweight="bold", loc="left", pad=8)

    h = [plt.Line2D([], [], marker="o", ls="", ms=8, color=S1, label="without blueprint"),
         plt.Line2D([], [], marker="o", ls="", ms=8, color=S2, label="with blueprint")]
    axes[0].legend(handles=h, loc="upper left", bbox_to_anchor=(0, -0.17), ncol=2,
                   frameon=False, fontsize=9.5, labelcolor=INK_2)
    fig.text(0.012, 0.972, "What it cost, run by run", fontsize=14, color=INK,
             fontweight="bold", va="top")
    fig.text(0.012, 0.922, "The blueprint adds tokens and takes away time - and the spread "
                           "matters as much as the middle.",
             fontsize=9.5, color=INK_2, va="top")
    fig.tight_layout(rect=(0, 0.10, 1, 0.895))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", default="/scratch/yuvraj17/stratatrace/results/q2-full")
    ap.add_argument("--out-dir", required=True)
    # same substitution as q2_onefile: the pre-fix anomaly_net cells measure a false recipe
    ap.add_argument("--override", default="", help="problem=dir, comma-separated")
    a = ap.parse_args()

    rows = load(a.full)
    for spec in [x for x in a.override.split(",") if x.strip()]:
        prob, d = spec.split("=", 1)
        repl = [r for r in load(d) if r.get("problem") == prob]
        if repl:
            rows = [r for r in rows if r.get("problem") != prob] + repl
            print("substituted %s from %s (%d runs)" % (prob, d, len(repl)))
    if not rows:
        print("no runs under %s" % a.full)
        return 1
    os.makedirs(a.out_dir, exist_ok=True)
    made = [
        chart_effect(rows, os.path.join(a.out_dir, "1-blueprint-effect.png")),
        chart_every_run(rows, os.path.join(a.out_dir, "2-every-run.png")),
        chart_window_raw(rows, os.path.join(a.out_dir, "3-window-raw.png")),
        chart_ceiling(rows, os.path.join(a.out_dir, "4-room-to-improve.png")),
        chart_cost_raw(rows, os.path.join(a.out_dir, "5-cost-raw.png")),
    ]
    for m in made:
        print("wrote %s  (%d KB)" % (m, os.path.getsize(m) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
