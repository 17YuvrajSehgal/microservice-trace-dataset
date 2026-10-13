#!/usr/bin/env python3
"""Figure for the LLM-share result (Phase 1): how much of wall is spent
waiting on the model, and how that share shrinks as the CPU cap tightens.
Numbers from llm_wait.py medians, n=5 per cell."""
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
t2 = [88.2, 91.5, 78.6, 70.7]
t3 = [81.0, 80.4, 68.8, 52.6]

fig, ax = plt.subplots(figsize=(4.4, 2.9))
ax.axhline(80, color=GREY, ls=":", lw=1.1)
ax.text(0.02, 82, "80%", color=GREY, fontsize=7.5)
ax.plot(x, t2, "-o", color=BLUE, label="bug-fix")
ax.plot(x, t3, "-s", color=ORANGE, label="implement")
ax.set_xticks(list(x)); ax.set_xticklabels(caps, rotation=20, ha="right")
ax.set_xlabel("cpu.max"); ax.set_ylabel("% of wall waiting on the model")
ax.set_ylim(40, 100); ax.legend(frameon=False, loc="lower left")
ax.set_title("LLM-bound by default, OS-bound under a tight cap", fontsize=9.5)
for ext in ("pdf", "png"):
    fig.savefig(OUT / f"fig_llmshare.{ext}")
print("wrote fig_llmshare")
