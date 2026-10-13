#!/usr/bin/env python3
"""Cross-agent consistency figure (Phase 2): Claude vs Codex, t3 task.
Both agents show the same throttle ladder and the same drop in the model's
share of wall as cpu.max tightens. Medians, n=5 (Claude) / n=3 (Codex)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path(__file__).resolve().parent / "figures"
BLUE, ORANGE, GREY = "#0072B2", "#E69F00", "#9aa0a6"
plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 9, "axes.labelsize": 9,
    "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.6,
    "axes.axisbelow": True, "figure.dpi": 150, "savefig.bbox": "tight",
    "lines.linewidth": 2, "lines.markersize": 6,
})
caps = ["uncapped", "1 core", "0.5 core", "0.25 core"]
x = range(len(caps))
# medians, Claude n=5 / Codex n=5 (full-parity campaign), implement task
thr_cl, thr_cx = [0.0, 0.5, 6.3, 19.8], [0.0, 0.2, 3.6, 18.7]
mod_cl, mod_cx = [81, 80, 69, 53], [89, 88, 79, 62]

fig, (axt, axm) = plt.subplots(1, 2, figsize=(7.0, 2.8))
axt.plot(x, thr_cl, "-o", color=BLUE, label="Claude")
axt.plot(x, thr_cx, "--s", color=ORANGE, label="Codex")
axt.set_title("(a) CFS throttle"); axt.set_ylabel("seconds throttled")
axt.legend(frameon=False, loc="upper left")
axm.plot(x, mod_cl, "-o", color=BLUE, label="Claude")
axm.plot(x, mod_cx, "--s", color=ORANGE, label="Codex")
axm.set_title("(b) share of wall waiting on the model")
axm.set_ylabel("% of wall"); axm.set_ylim(40, 100)
for ax in (axt, axm):
    ax.set_xticks(list(x)); ax.set_xticklabels(caps, rotation=20, ha="right")
    ax.set_xlabel("cpu.max")
fig.suptitle("Cross-agent consistency (Claude vs Codex, implement task)",
             fontsize=9.5, y=1.02)
for ext in ("pdf", "png"):
    fig.savefig(OUT / f"fig_consistency.{ext}")
print("wrote fig_consistency")
